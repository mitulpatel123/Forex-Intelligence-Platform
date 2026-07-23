from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil
import structlog
import typer
import uvicorn
from adapter_sdk import ProviderEnvelope
from event_bus import RedisEventBus
from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from forex_contracts import AdapterState, AdapterStatus, RawProviderEvent
from forex_contracts.models import canonical_hash
from ic_markets_adapter import IcMarketsAdapter
from ic_markets_adapter.redaction import redact
from observability import METRICS
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict, Field
from storage import PostgresStorage

from forex_collector.pipeline import Pipeline
from forex_collector.settings import Settings

cli = typer.Typer()
logger = structlog.get_logger()


class BridgeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    connection_id: str
    session_id: str
    received_at: datetime
    semantics: str
    payload: dict[str, Any]
    channel_metadata: dict[str, Any] = {}


class DiscoveryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=8, max_length=128)
    connection_id: str
    session_id: str
    frame: dict[str, Any]


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
        "last_event": None,
        "last_tick": None,
        "components": {},
        "bridge_sessions": {},
        "bridge_reconnect_count": 0,
        "bridge_seen": False,
    }

    def bridge_health() -> dict[str, Any]:
        now = datetime.now(UTC)
        sessions = state["bridge_sessions"]
        for session_id, session in list(sessions.items()):
            if (now - session["last_message"]).total_seconds() > 3_600:
                del sessions[session_id]
        fresh_sessions = [
            session
            for session in sessions.values()
            if (now - session["last_message"]).total_seconds() <= config.bridge_stale_after_seconds
        ]
        ready_sessions = [session for session in fresh_sessions if session["observer_ready"]]
        last_browser_message = max(
            (session["last_message"] for session in sessions.values()),
            default=None,
        )
        outbox_fields = [
            "outbox_pending",
            "outbox_produced",
            "outbox_acknowledged",
            "outbox_retries",
            "outbox_dropped",
            "outbox_rejected",
        ]
        counters = {
            field: max((session[field] for session in fresh_sessions), default=0)
            for field in outbox_fields
        }
        return {
            "connected": bool(ready_sessions),
            "observer_ready": bool(ready_sessions),
            "last_browser_message": last_browser_message,
            "last_browser_message_age_seconds": (
                (now - last_browser_message).total_seconds()
                if last_browser_message is not None
                else None
            ),
            **counters,
        }

    def current_adapter_state() -> tuple[AdapterState, str, bool, float | None]:
        bridge = bridge_health()
        last_tick = state["last_tick"]
        tick_age = (
            (datetime.now(UTC) - last_tick).total_seconds() if last_tick is not None else None
        )
        if not bridge["connected"]:
            return (
                AdapterState.DISCONNECTED,
                "Browser bridge heartbeat is not fresh",
                False,
                tick_age,
            )
        if last_tick is None:
            return (
                AdapterState.INITIALIZING,
                "Browser observer is ready and waiting for the first valid quote",
                True,
                tick_age,
            )
        if tick_age is not None and tick_age > config.stale_after_seconds:
            return (
                AdapterState.DEGRADED,
                "Browser bridge is connected but the feed is stale",
                True,
                tick_age,
            )
        return AdapterState.CONNECTED, "Validated display quotes are flowing", True, tick_age

    def touch_bridge_session(
        connection_id: str,
        session_id: str,
        *,
        observer_ready: bool = True,
        counters: dict[str, int] | None = None,
    ) -> None:
        was_connected = bridge_health()["connected"]
        existing = state["bridge_sessions"].get(session_id, {})
        state["bridge_sessions"][session_id] = {
            "connection_id": connection_id,
            "last_message": datetime.now(UTC),
            "observer_ready": observer_ready,
            "outbox_pending": (counters or {}).get(
                "outbox_pending", existing.get("outbox_pending", 0)
            ),
            "outbox_produced": (counters or {}).get(
                "outbox_produced", existing.get("outbox_produced", 0)
            ),
            "outbox_acknowledged": (counters or {}).get(
                "outbox_acknowledged", existing.get("outbox_acknowledged", 0)
            ),
            "outbox_retries": (counters or {}).get(
                "outbox_retries", existing.get("outbox_retries", 0)
            ),
            "outbox_dropped": (counters or {}).get(
                "outbox_dropped", existing.get("outbox_dropped", 0)
            ),
            "outbox_rejected": (counters or {}).get(
                "outbox_rejected", existing.get("outbox_rejected", 0)
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
            queue: asyncio.Queue[tuple[ProviderEnvelope, asyncio.Future[tuple[int, int]]]] = (
                asyncio.Queue(maxsize=config.queue_size)
            )
            state["queue"] = queue

            async def queue_worker() -> None:
                while True:
                    envelope, future = await queue.get()
                    try:
                        output = await state["pipeline"].process(envelope)
                        result = (1 if output.tick else 0, len(output.quality_events))
                        if not future.done():
                            future.set_result(result)
                    except Exception as exc:
                        if not future.done():
                            future.set_exception(exc)
                    finally:
                        queue.task_done()
                        METRICS.collector_queue_depth.set(queue.qsize())

            async def heartbeat_worker() -> None:
                process = psutil.Process()
                while True:
                    adapter_state, summary, connected, _ = current_adapter_state()
                    bridge = bridge_health()
                    state["components"]["adapter"] = adapter_state.value
                    heartbeat = AdapterStatus(
                        instance_id="icm-local-01",
                        state=adapter_state,
                        connection_count=1 if connected else 0,
                        reconnect_count=state["bridge_reconnect_count"],
                        last_message_time=bridge["last_browser_message"],
                        last_valid_tick_time=state["last_tick"],
                        summary=summary,
                    )
                    await storage.store_heartbeat(heartbeat)
                    await bus.publish("adapter.status", heartbeat)
                    METRICS.adapter_connected.set(1 if connected else 0)
                    METRICS.bridge_connected.set(1 if bridge["connected"] else 0)
                    METRICS.observer_ready.set(1 if bridge["observer_ready"] else 0)
                    METRICS.browser_outbox_pending.set(bridge["outbox_pending"])
                    METRICS.browser_outbox_dropped_total.set(bridge["outbox_dropped"])
                    METRICS.browser_outbox_retries_total.set(bridge["outbox_retries"])
                    METRICS.browser_outbox_acknowledged_total.set(bridge["outbox_acknowledged"])
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

    app = FastAPI(title="Forex Collector", version="0.1.0", lifespan=lifespan)

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
        adapter_state, _, _, age = current_adapter_state()
        bridge = bridge_health()
        state["components"]["adapter"] = adapter_state.value
        return {
            "components": state["components"],
            "bridge": bridge,
            "feed": {
                "status": (
                    "STALE" if age is None or age > config.stale_after_seconds else "HEALTHY"
                ),
                "last_valid_tick_age_seconds": age,
            },
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
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="loopback clients only")
        if not secrets.compare_digest(x_bridge_token or "", state["token"]):
            raise HTTPException(status_code=401, detail="invalid bridge token")
        touch_bridge_session(
            message.connection_id,
            message.session_id,
            observer_ready=message.observer_ready,
            counters={
                "outbox_pending": message.outbox_pending,
                "outbox_produced": message.outbox_produced,
                "outbox_acknowledged": message.outbox_acknowledged,
                "outbox_retries": message.outbox_retries,
                "outbox_dropped": message.outbox_dropped,
                "outbox_rejected": message.outbox_rejected,
            },
        )
        return {"accepted": True, "server_time": datetime.now(UTC)}

    @app.post("/ingest/provider")
    async def ingest(
        message: BridgeMessage,
        request: Request,
        x_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="loopback clients only")
        if not secrets.compare_digest(x_bridge_token or "", state["token"]):
            raise HTTPException(status_code=401, detail="invalid bridge token")
        if message.semantics not in {"snapshot", "partial"}:
            raise HTTPException(status_code=422, detail="semantics must be snapshot or partial")
        touch_bridge_session(message.connection_id, message.session_id)
        if await state["storage"].has_raw(message.event_id):
            return {
                "accepted": True,
                "duplicate": True,
                "event_id": message.event_id,
                "valid_ticks": 0,
                "quality_events": 0,
            }
        envelope = ProviderEnvelope(
            event_id=message.event_id,
            connection_id=message.connection_id,
            session_id=message.session_id,
            received_at=message.received_at,
            semantics=message.semantics,  # type: ignore[arg-type]
            payload=message.payload,
            channel_metadata=message.channel_metadata,
        )
        loop = asyncio.get_running_loop()
        result: asyncio.Future[tuple[int, int]] = loop.create_future()
        try:
            await asyncio.wait_for(state["queue"].put((envelope, result)), timeout=0.25)
        except TimeoutError as exc:
            METRICS.collector_dropped_events_total.inc()
            raise HTTPException(status_code=503, detail="bounded ingestion queue full") from exc
        METRICS.collector_queue_depth.set(state["queue"].qsize())
        valid, quality = await result
        state["last_event"] = datetime.now(UTC)
        if valid:
            state["last_tick"] = datetime.now(UTC)
        return {
            "accepted": True,
            "duplicate": False,
            "event_id": message.event_id,
            "valid_ticks": valid,
            "quality_events": quality,
        }

    @app.post("/ingest/discovery")
    async def ingest_discovery(
        message: DiscoveryMessage,
        request: Request,
        x_bridge_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="loopback clients only")
        if not secrets.compare_digest(x_bridge_token or "", state["token"]):
            raise HTTPException(status_code=401, detail="invalid bridge token")
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
        state["last_event"] = datetime.now(UTC)
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
