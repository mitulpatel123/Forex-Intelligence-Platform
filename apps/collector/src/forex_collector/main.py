from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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
from observability import METRICS
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, ConfigDict
from storage import PostgresStorage

from forex_collector.pipeline import Pipeline
from forex_collector.settings import Settings

cli = typer.Typer()
logger = structlog.get_logger()


class BridgeMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str
    session_id: str
    received_at: datetime
    semantics: str
    payload: dict[str, Any]
    channel_metadata: dict[str, Any] = {}


class DiscoveryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connection_id: str
    session_id: str
    frame: dict[str, Any]


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
    }

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
                    last_tick = state["last_tick"]
                    tick_age = datetime.now(UTC) - last_tick if last_tick is not None else None
                    if last_tick is None:
                        adapter_state = AdapterState.BLOCKED_BY_PROVIDER_DISCOVERY
                        summary = "Waiting for the first validated live EUR/USD quote"
                        connected = 0
                    elif tick_age is not None and tick_age > timedelta(
                        seconds=config.stale_after_seconds
                    ):
                        adapter_state = AdapterState.DEGRADED
                        summary = "Live EUR/USD bridge connected but the latest tick is stale"
                        connected = 1
                    else:
                        adapter_state = AdapterState.CONNECTED
                        summary = "Validated live EUR/USD quotes are flowing"
                        connected = 1
                    state["components"]["adapter"] = adapter_state.value
                    heartbeat = AdapterStatus(
                        instance_id="icm-local-01",
                        state=adapter_state,
                        last_message_time=state["last_event"],
                        last_valid_tick_time=last_tick,
                        summary=summary,
                    )
                    await storage.store_heartbeat(heartbeat)
                    await bus.publish("adapter.status", heartbeat)
                    METRICS.adapter_connected.set(connected)
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
                "adapter": "BLOCKED_BY_PROVIDER_DISCOVERY",
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
        last_tick = state["last_tick"]
        age = (datetime.now(UTC) - last_tick).total_seconds() if last_tick is not None else None
        if age is None:
            state["components"]["adapter"] = AdapterState.BLOCKED_BY_PROVIDER_DISCOVERY.value
        elif age > config.stale_after_seconds:
            state["components"]["adapter"] = AdapterState.DEGRADED.value
        else:
            state["components"]["adapter"] = AdapterState.CONNECTED.value
        return {
            "components": state["components"],
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
        envelope = ProviderEnvelope(
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
        return {"accepted": True, "valid_ticks": valid, "quality_events": quality}

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
        payload = message.frame
        raw = RawProviderEvent(
            adapter_instance_id="icm-discovery-bridge",
            connection_id=message.connection_id,
            session_id=message.session_id,
            received_at=datetime.now(UTC),
            payload_content_type="application/json",
            payload=payload,
            content_hash=canonical_hash(payload),
            channel_metadata={"purpose": "provider_discovery"},
            redaction_status="SANITIZED",
        )
        await state["storage"].store_raw(raw)
        await state["bus"].publish("raw.provider.ic_markets", raw)
        state["last_event"] = datetime.now(UTC)
        return {"accepted": True, "raw_event_id": raw.event_id}

    return app


@cli.command()
def serve() -> None:
    structlog.configure(processors=[structlog.processors.JSONRenderer()])
    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.health_port)


if __name__ == "__main__":
    cli()
