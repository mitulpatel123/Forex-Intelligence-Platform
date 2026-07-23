from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from adapter_sdk import ProviderEnvelope
from event_bus import RedisEventBus
from forex_collector.pipeline import Pipeline
from forex_collector.settings import Settings
from forex_contracts import AdapterState, AdapterStatus
from ic_markets_adapter import IcMarketsAdapter
from storage import PostgresStorage


@pytest.mark.asyncio
async def test_real_redis_and_timescale_vertical_slice() -> None:
    settings = Settings()
    bus = RedisEventBus(settings.redis_url)
    storage = PostgresStorage(settings.database_url)
    await storage.open()
    try:
        await storage.migrate(Path(__file__).resolve().parents[2] / "migrations")
        await bus.reset_test_state()
        await storage.reset_test_state()
        pipeline = Pipeline(IcMarketsAdapter(), bus, storage)
        received = datetime.now(UTC) - timedelta(milliseconds=2)
        envelope = ProviderEnvelope(
            connection_id="integration",
            session_id="integration",
            received_at=received,
            semantics="snapshot",
            payload={
                "instrument": "EURUSD",
                "provider_event_time": (received - timedelta(milliseconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
                "sequence": 1,
                "bid": "1.08542",
                "ask": "1.08544",
            },
        )
        output = await pipeline.process(envelope)
        assert output.tick is not None
        assert await bus.redis.get("latest:quote:IC_MARKETS:EURUSD")
        assert await bus.redis.xlen("raw.provider.ic_markets") == 1
        assert await bus.redis.xlen("normalized.price_tick") == 1

        async with storage.pool.connection() as connection:
            raw_count = await (
                await connection.execute("SELECT count(*) FROM raw_provider_events")
            ).fetchone()
            tick_count = await (
                await connection.execute("SELECT count(*) FROM price_ticks")
            ).fetchone()
        assert raw_count == (1,)
        assert tick_count == (1,)

        await storage.store_tick(output.tick)
        async with storage.pool.connection() as connection:
            idempotent_count = await (
                await connection.execute("SELECT count(*) FROM price_ticks")
            ).fetchone()
        assert idempotent_count == (1,)

        crossed = ProviderEnvelope(
            connection_id="integration",
            session_id="integration",
            received_at=received + timedelta(milliseconds=5),
            semantics="snapshot",
            payload={
                "instrument": "EURUSD",
                "provider_event_time": received.isoformat().replace("+00:00", "Z"),
                "sequence": 2,
                "bid": "1.2",
                "ask": "1.1",
            },
        )
        bad_output = await pipeline.process(crossed)
        assert bad_output.tick is None
        assert await bus.redis.xlen("quality.events") == 1

        heartbeat = AdapterStatus(
            instance_id="integration",
            state=AdapterState.BLOCKED_BY_PROVIDER_DISCOVERY,
            summary="integration heartbeat",
        )
        await storage.store_heartbeat(heartbeat)
        async with storage.pool.connection() as connection:
            quality_count = await (
                await connection.execute("SELECT count(*) FROM data_quality_events")
            ).fetchone()
            heartbeat_count = await (
                await connection.execute("SELECT count(*) FROM adapter_heartbeats")
            ).fetchone()
        assert quality_count == (1,)
        assert heartbeat_count == (1,)

        await bus.ensure_group("normalized.price_tick", "integration-consumers")
        messages = await bus.consume(
            "normalized.price_tick", "integration-consumers", "consumer-1", block_ms=1
        )
        assert len(messages) == 1
        await bus.acknowledge("normalized.price_tick", "integration-consumers", messages[0][0])

        await bus.close()
        restarted_bus = RedisEventBus(settings.redis_url)
        assert await restarted_bus.ping()
        assert await restarted_bus.redis.get("latest:quote:IC_MARKETS:EURUSD")
        await restarted_bus.close()
    finally:
        await storage.close()
