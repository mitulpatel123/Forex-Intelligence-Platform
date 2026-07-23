from __future__ import annotations

import asyncio
import json
import secrets
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import psutil
import structlog
import typer
import uvicorn
from adapter_sdk import ProviderEnvelope
from event_bus import RedisEventBus
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from forex_contracts import (
    SUPPORTED_INSTRUMENTS,
    AdapterState,
    AdapterStatus,
    QualityStatus,
    RawProviderEvent,
    SupportedInstrument,
)
from forex_contracts.models import canonical_hash
from ic_markets_adapter import IcMarketsAdapter
from ic_markets_adapter.redaction import redact
from observability import METRICS
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field, model_validator
from storage import PostgresStorage

from forex_collector.fair_queue import FairInstrumentQueue
from forex_collector.pipeline import Pipeline
from forex_collector.settings import Settings

cli = typer.Typer()
logger = structlog.get_logger()


class BridgeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    instrument: SupportedInstrument
    browser_run_id: str = Field(min_length=8, max_length=128)
    tab_id: int
    frame_id: int
    document_session_id: str = Field(min_length=8, max_length=128)
    connection_id: str
    session_id: str
    received_at: datetime
    semantics: Literal["snapshot"]
    payload: dict[str, Any]
    channel_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def instrument_matches_payload(self) -> BridgeMessage:
        if self.payload.get("instrument") != self.instrument:
            raise ValueError("top-level and payload instruments must match")
        return self


class DiscoveryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    connection_id: str
    session_id: str
    frame: dict[str, Any]


class PairHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: Literal["FOUND", "READY", "MISSING", "AMBIGUOUS", "STALE"]
    last_observation_time: datetime | None = None
    outbox_pending: int = Field(ge=0)
    outbox_produced: int = Field(ge=0)
    outbox_acknowledged: int = Field(ge=0)
    outbox_retries: int = Field(ge=0)
    outbox_dropped: int = Field(ge=0)
    outbox_rejected: int = Field(ge=0)


class BridgeHeartbeat(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str = Field(min_length=8, max_length=200)
    session_id: str = Field(min_length=8, max_length=200)
    observer_ready: bool
    bridge_state: str = Field(max_length=64)
    outbox_pending: int = Field(ge=0)
    outbox_produced: int = Field(ge=0)
    outbox_acknowledged: int = Field(ge=0)
    outbox_retries: int = Field(ge=0)
    outbox_dropped: int = Field(ge=0)
    outbox_rejected: int = Field(ge=0)
    pairs: dict[SupportedInstrument, PairHeartbeat]

    @model_validator(mode="after")
    def has_exact_supported_pairs(self) -> BridgeHeartbeat:
        if set(self.pairs) != set(SUPPORTED_INSTRUMENTS):
            raise ValueError("heartbeat must contain exactly the four supported instruments")
        return self


def ensure_token(path_string: str) -> str:
    path = Path(path_string)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    state: dict[str, Any] = {
        "ready": False,
        "live": True,
        "components": {},
        "bridge_sessions": {},
        "bridge_reconnect_count": 0,
        "bridge_seen": False,
        "last_tick": {instrument: None for instrument in SUPPORTED_INSTRUMENTS},
        "recent_observations": {
            instrument: deque(maxlen=10_000) for instrument in SUPPORTED_INSTRUMENTS
        },
        "pair_counters": {
            instrument: {
                "invalid_events": 0,
                "duplicate_events": 0,
                "out_of_order_events": 0,
                "stale_events": 0,
            }
            for instrument in SUPPORTED_INSTRUMENTS
        },
    }

    def bridge_health() -> dict[str, Any]:
        now = datetime.now(UTC)
        sessions = state["bridge_sessions"]
        for session_id, session in list(sessions.items()):
            if (now - session["last_message"]).total_seconds() > 3_600:
                del sessions[session_id]
        fresh = [
            session
            for session in sessions.values()
            if (now - session["last_message"]).total_seconds() <= config.bridge_stale_after_seconds
        ]
        ready = [session for session in fresh if session["observer_ready"]]
        last_message = max(
            (session["last_message"] for session in sessions.values()),
            default=None,
        )
        total_fields = (
            "outbox_pending",
            "outbox_produced",
            "outbox_acknowledged",
            "outbox_retries",
            "outbox_dropped",
            "outbox_rejected",
        )
        totals = {
            field: max((session[field] for session in fresh), default=0) for field in total_fields
        }
        priority = {"MISSING": 0, "FOUND": 1, "READY": 2, "STALE": 2, "AMBIGUOUS": 3}
        pairs: dict[str, dict[str, Any]] = {}
        for instrument in SUPPORTED_INSTRUMENTS:
            candidates = [session["pairs"][instrument] for session in fresh]
            selected = max(
                candidates, key=lambda pair: priority.get(pair["target_status"], 0), default=None
            )
            pairs[instrument] = {
                "target_status": selected["target_status"] if selected else "MISSING",
                "last_observation_time": max(
                    (
                        pair["last_observation_time"]
                        for pair in candidates
                        if pair["last_observation_time"] is not None
                    ),
                    default=None,
                ),
                **{
                    field: max((pair[field] for pair in candidates), default=0)
                    for field in total_fields
                },
            }
        return {
            "connected": bool(ready),
            "observer_ready": bool(ready),
            "observer_documents": len(fresh),
            "last_browser_message": last_message,
            "last_browser_message_age_seconds": (
                (now - last_message).total_seconds() if last_message else None
            ),
            **totals,
            "pairs": pairs,
        }

    def pair_health(bridge: dict[str, Any]) -> dict[str, dict[str, Any]]:
        now = datetime.now(UTC)
        result: dict[str, dict[str, Any]] = {}
        for instrument in SUPPORTED_INSTRUMENTS:
            browser = bridge["pairs"][instrument]
            last_tick = state["last_tick"][instrument]
            age = (now - last_tick).total_seconds() if last_tick else None
            target = browser["target_status"]
            if target == "AMBIGUOUS":
                pair_status = "AMBIGUOUS"
            elif target == "MISSING":
                pair_status = "MISSING"
            elif last_tick is None:
                pair_status = "INITIALIZING"
            elif target == "STALE" or (age is not None and age > config.stale_after_seconds):
                pair_status = "STALE"
            else:
                pair_status = "HEALTHY"
            cutoff = now - timedelta(seconds=60)
            observations: deque[datetime] = state["recent_observations"][instrument]
            while observations and observations[0] < cutoff:
                observations.popleft()
            result[instrument] = {
                "target_found": target in {"FOUND", "READY", "STALE"},
                "observer_ready": target in {"FOUND", "READY", "STALE"},
                "last_observation_time": browser["last_observation_time"],
                "last_valid_tick_time": last_tick,
                "last_valid_tick_age_seconds": age,
                "event_rate": len(observations) / 60,
                "outbox_pending": browser["outbox_pending"],
                "outbox_produced": browser["outbox_produced"],
                "outbox_acknowledged": browser["outbox_acknowledged"],
                "outbox_retries": browser["outbox_retries"],
                "outbox_dropped": browser["outbox_dropped"],
                "outbox_rejected": browser["outbox_rejected"],
                **state["pair_counters"][instrument],
                "status": pair_status,
            }
        return result

    def current_adapter_state() -> tuple[AdapterState, str, bool, dict[str, Any], dict[str, Any]]:
        bridge = bridge_health()
        pairs = pair_health(bridge)
        if not bridge["connected"]:
            return (
                AdapterState.DISCONNECTED,
                "Browser bridge heartbeat is not fresh",
                False,
                bridge,
                pairs,
            )
        statuses = [pair["status"] for pair in pairs.values()]
        if all(pair_status in {"MISSING", "INITIALIZING"} for pair_status in statuses):
            return (
                AdapterState.INITIALIZING,
                "Browser connected; waiting for supported Market Watch rows",
                True,
                bridge,
                pairs,
            )
        if all(pair_status == "HEALTHY" for pair_status in statuses):
            return (
                AdapterState.CONNECTED,
                "All four display quotes are healthy",
                True,
                bridge,
                pairs,
            )
        return (
            AdapterState.DEGRADED,
            "One or more display quotes are missing, ambiguous, stale, or unhealthy",
            True,
            bridge,
            pairs,
        )

    def touch_bridge_session(
        connection_id: str,
        session_id: str,
        *,
        observer_ready: bool | None = None,
        heartbeat: BridgeHeartbeat | None = None,
    ) -> None:
        was_connected = bridge_health()["connected"]
        existing = state["bridge_sessions"].get(session_id, {})
        empty_pairs = {
            instrument: {
                "target_status": "MISSING",
                "last_observation_time": None,
                "outbox_pending": 0,
                "outbox_produced": 0,
                "outbox_acknowledged": 0,
                "outbox_retries": 0,
                "outbox_dropped": 0,
                "outbox_rejected": 0,
            }
            for instrument in SUPPORTED_INSTRUMENTS
        }
        state["bridge_sessions"][session_id] = {
            "connection_id": connection_id,
            "last_message": datetime.now(UTC),
            "observer_ready": (
                heartbeat.observer_ready
                if heartbeat
                else observer_ready
                if observer_ready is not None
                else existing.get("observer_ready", False)
            ),
            **{
                field: (getattr(heartbeat, field) if heartbeat else existing.get(field, 0))
                for field in (
                    "outbox_pending",
                    "outbox_produced",
                    "outbox_acknowledged",
                    "outbox_retries",
                    "outbox_dropped",
                    "outbox_rejected",
                )
            },
            "pairs": (
                {
                    instrument: heartbeat.pairs[instrument].model_dump()
                    for instrument in SUPPORTED_INSTRUMENTS
                }
                if heartbeat
                else existing.get("pairs", empty_pairs)
            ),
        }
        if len(state["bridge_sessions"]) > 100:
            oldest = min(
                state["bridge_sessions"],
                key=lambda key: state["bridge_sessions"][key]["last_message"],
            )
            del state["bridge_sessions"][oldest]
        is_connected = bridge_health()["connected"]
        if is_connected and not was_connected and state["bridge_seen"]:
            state["bridge_reconnect_count"] += 1
            METRICS.adapter_reconnect_total.inc()
        if is_connected:
            state["bridge_seen"] = True

    def require_bridge_access(request: Request, token: str | None) -> None:
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="loopback clients only")
        if not secrets.compare_digest(token or "", state["token"]):
            raise HTTPException(status_code=401, detail="invalid bridge token")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        bus = RedisEventBus(config.redis_url)
        storage = PostgresStorage(config.database_url)
        worker_task: asyncio.Task[None] | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            redis_ok = await bus.ping()
            await storage.open()
            database_ok = await storage.ping()
            migrations = Path(__file__).resolve().parents[4] / "migrations"
            await storage.migrate(migrations)
            state["bus"] = bus
            state["storage"] = storage
            state["pipeline"] = Pipeline(IcMarketsAdapter(), bus, storage)
            queue: FairInstrumentQueue[
                tuple[ProviderEnvelope, asyncio.Future[tuple[int, list[QualityStatus]]]]
            ] = FairInstrumentQueue(config.queue_size)
            state["queue"] = queue

            async def queue_worker() -> None:
                while True:
                    instrument, (envelope, future) = await queue.get()
                    try:
                        output = await state["pipeline"].process(envelope)
                        result = (
                            1 if output.tick else 0,
                            [quality.classification for quality in output.quality_events],
                        )
                        if not future.done():
                            future.set_result(result)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    finally:
                        queue.task_done(instrument)
                        METRICS.collector_queue_depth.labels(instrument).set(
                            queue.depth(instrument)
                        )

            async def heartbeat_worker() -> None:
                process = psutil.Process()
                while True:
                    adapter_state, summary, connected, bridge, pairs = current_adapter_state()
                    state["components"]["adapter"] = adapter_state.value
                    last_ticks = [tick for tick in state["last_tick"].values() if tick is not None]
                    heartbeat = AdapterStatus(
                        instance_id="icm-local-01",
                        state=adapter_state,
                        connection_count=1 if connected else 0,
                        reconnect_count=state["bridge_reconnect_count"],
                        last_message_time=bridge["last_browser_message"],
                        last_valid_tick_time=max(last_ticks, default=None),
                        summary=summary,
                    )
                    await storage.store_heartbeat(heartbeat)
                    await bus.publish("adapter.status", heartbeat)
                    METRICS.adapter_connected.set(
                        1 if adapter_state == AdapterState.CONNECTED else 0
                    )
                    METRICS.bridge_connected.set(1 if bridge["connected"] else 0)
                    METRICS.observer_ready.set(1 if bridge["observer_ready"] else 0)
                    for instrument in SUPPORTED_INSTRUMENTS:
                        pair = pairs[instrument]
                        METRICS.browser_outbox_pending.labels(instrument).set(
                            pair["outbox_pending"]
                        )
                        METRICS.browser_outbox_produced_total.labels(instrument).set(
                            pair["outbox_produced"]
                        )
                        METRICS.browser_outbox_acknowledged_total.labels(instrument).set(
                            pair["outbox_acknowledged"]
                        )
                        METRICS.browser_outbox_retries_total.labels(instrument).set(
                            pair["outbox_retries"]
                        )
                        METRICS.browser_outbox_dropped_total.labels(instrument).set(
                            pair["outbox_dropped"]
                        )
                        METRICS.browser_outbox_rejected_total.labels(instrument).set(
                            pair["outbox_rejected"]
                        )
                        if pair["last_valid_tick_age_seconds"] is not None:
                            METRICS.last_valid_tick_age_seconds.labels(instrument).set(
                                pair["last_valid_tick_age_seconds"]
                            )
                        await bus.set_feed_health(instrument, pair)
                    METRICS.collector_process_cpu_percent.set(process.cpu_percent())
                    METRICS.collector_process_memory_bytes.set(process.memory_info().rss)
                    await asyncio.sleep(5)

            worker_task = asyncio.create_task(queue_worker())
            heartbeat_task = asyncio.create_task(heartbeat_worker())
            state["token"] = ensure_token(config.bridge_token_file)
            state["components"] = {
                "redis": "UP" if redis_ok else "DOWN",
                "timescaledb": "UP" if database_ok else "DOWN",
                "migrations": "CURRENT",
                "adapter": "DISCONNECTED",
            }
            state["ready"] = redis_ok and database_ok
            logger.info("collector_started", bind_host=config.bind_host)
            yield
        finally:
            state["ready"] = False
            if "queue" in state:
                await state["queue"].join()
            for task in (worker_task, heartbeat_task):
                if task:
                    task.cancel()
            if worker_task or heartbeat_task:
                await asyncio.gather(
                    *(task for task in (worker_task, heartbeat_task) if task),
                    return_exceptions=True,
                )
            if "bus" in state:
                await state["bus"].close()
            if "storage" in state:
                await state["storage"].close()

    app = FastAPI(title="Forex Collector", version="0.2.0", lifespan=lifespan)

    @app.get("/health/live")
    async def live() -> dict[str, Any]:
        return {"status": "UP" if state["live"] else "DOWN", "event_loop": "responsive"}

    @app.get("/health/ready")
    async def ready() -> Response:
        code = status.HTTP_200_OK if state["ready"] else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(
            json.dumps({"status": "READY" if state["ready"] else "NOT_READY"}),
            status_code=code,
            media_type="application/json",
        )

    @app.get("/health/components")
    async def components() -> dict[str, Any]:
        adapter_state, _, _, bridge, pairs = current_adapter_state()
        state["components"]["adapter"] = adapter_state.value
        return {
            "components": state["components"],
            "bridge": bridge,
            "pairs": pairs,
        }

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/ingest/bridge-heartbeat")
    async def ingest_bridge_heartbeat(
        message: BridgeHeartbeat,
        request: Request,
        x_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_bridge_access(request, x_bridge_token)
        touch_bridge_session(
            message.connection_id,
            message.session_id,
            heartbeat=message,
        )
        return {"accepted": True, "server_time": datetime.now(UTC)}

    @app.post("/ingest/provider")
    async def ingest(
        message: BridgeMessage,
        request: Request,
        x_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_bridge_access(request, x_bridge_token)
        if message.semantics != "snapshot":
            raise HTTPException(
                status_code=422,
                detail="visible display observations must be full snapshots",
            )
        touch_bridge_session(message.connection_id, message.session_id)
        if await state["storage"].has_raw(message.event_id):
            return {
                "accepted": True,
                "duplicate": True,
                "event_id": message.event_id,
                "instrument": message.instrument,
                "valid_ticks": 0,
                "quality_events": 0,
            }
        envelope = ProviderEnvelope(
            event_id=message.event_id,
            connection_id=message.connection_id,
            session_id=message.session_id,
            received_at=message.received_at,
            semantics="snapshot",
            payload=message.payload,
            channel_metadata={
                **message.channel_metadata,
                "browser_run_id": message.browser_run_id,
                "tab_id": message.tab_id,
                "frame_id": message.frame_id,
                "document_session_id": message.document_session_id,
            },
        )
        loop = asyncio.get_running_loop()
        result: asyncio.Future[tuple[int, list[QualityStatus]]] = loop.create_future()
        try:
            await asyncio.wait_for(
                state["queue"].put(message.instrument, (envelope, result)),
                timeout=0.25,
            )
        except TimeoutError as exc:
            METRICS.collector_dropped_events_total.labels(message.instrument).inc()
            raise HTTPException(
                status_code=503,
                detail=f"bounded {message.instrument} ingestion queue full",
            ) from exc
        METRICS.collector_queue_depth.labels(message.instrument).set(
            state["queue"].depth(message.instrument)
        )
        valid, qualities = await result
        now = datetime.now(UTC)
        state["recent_observations"][message.instrument].append(now)
        METRICS.display_observations_total.labels(message.instrument).inc()
        if valid:
            state["last_tick"][message.instrument] = now
        counters = state["pair_counters"][message.instrument]
        for classification in qualities:
            if classification == QualityStatus.DUPLICATE:
                counters["duplicate_events"] += 1
            elif classification == QualityStatus.OUT_OF_ORDER:
                counters["out_of_order_events"] += 1
            elif classification == QualityStatus.STALE:
                counters["stale_events"] += 1
            elif classification in {QualityStatus.BAD, QualityStatus.UNPARSEABLE}:
                counters["invalid_events"] += 1
        return {
            "accepted": True,
            "duplicate": False,
            "event_id": message.event_id,
            "instrument": message.instrument,
            "valid_ticks": valid,
            "quality_events": len(qualities),
        }

    @app.post("/ingest/discovery")
    async def ingest_discovery(
        message: DiscoveryMessage,
        request: Request,
        x_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        require_bridge_access(request, x_bridge_token)
        touch_bridge_session(message.connection_id, message.session_id)
        if await state["storage"].has_raw(message.event_id):
            return {"accepted": True, "duplicate": True, "event_id": message.event_id}
        payload, redactions = redact(message.frame)
        assert isinstance(payload, dict)
        raw = RawProviderEvent(
            event_id=message.event_id,
            adapter_instance_id="icm-discovery-bridge",
            connection_id=message.connection_id,
            session_id=message.session_id,
            received_at=datetime.now(UTC),
            payload_content_type="application/json",
            payload=payload,
            content_hash=canonical_hash(payload),
            channel_metadata={
                "purpose": "provider_discovery",
                "server_side_redaction": True,
            },
            redaction_status="SANITIZED" if redactions else "NOT_REQUIRED",
            redactions=redactions,
        )
        await state["storage"].store_raw(raw)
        await state["bus"].publish("raw.provider.ic_markets", raw)
        return {
            "accepted": True,
            "duplicate": False,
            "event_id": message.event_id,
            "raw_event_id": raw.event_id,
        }

    return app


@cli.command()
def serve() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.health_port)


if __name__ == "__main__":
    cli()
