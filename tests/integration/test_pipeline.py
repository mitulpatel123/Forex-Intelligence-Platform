import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from adapter_sdk import ProviderEnvelope
from event_bus import RedisEventBus
from forex_collector.pipeline import Pipeline
from forex_collector.replay import replay_file
from forex_collector.settings import Settings
from forex_contracts import SUPPORTED_INSTRUMENTS, AdapterState, AdapterStatus
from ic_markets_adapter import IcMarketsAdapter
from storage import PostgresStorage

QUOTES = {
    "EURUSD": ("1.08542", "1.08544"),
    "GBPUSD": ("1.32042", "1.32044"),
    "USDJPY": ("163.842", "163.844"),
    "AUDUSD": ("0.69542", "0.69544"),
}


@pytest.mark.asyncio
async def test_real_redis_and_timescale_four_pair_vertical_slice() -> None:
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
        outputs = {}
        for index, instrument in enumerate(SUPPORTED_INSTRUMENTS, start=1):
            bid, ask = QUOTES[instrument]
            envelope = ProviderEnvelope(
                event_id=f"integration-{instrument.lower()}",
                connection_id="integration",
                session_id="integration",
                received_at=received + timedelta(microseconds=index),
                semantics="snapshot",
                payload={
                    "instrument": instrument,
                    "provider_event_time": (
                        received - timedelta(milliseconds=1) + timedelta(microseconds=index)
                    )
                    .isoformat()
                    .replace("+00:00", "Z"),
                    "sequence": 1,
                    "bid": bid,
                    "ask": ask,
                },
            )
            outputs[instrument] = await pipeline.process(envelope)
            assert outputs[instrument].tick is not None

        latest_payloads = {}
        for instrument in SUPPORTED_INSTRUMENTS:
            raw_latest = await bus.redis.get(f"latest:quote:IC_MARKETS:{instrument}")
            assert raw_latest
            latest_payloads[instrument] = json.loads(raw_latest)
            assert latest_payloads[instrument]["instrument"] == instrument
        assert len({payload["event_id"] for payload in latest_payloads.values()}) == 4
        assert await bus.redis.xlen("raw.provider.ic_markets") == 4
        assert await bus.redis.xlen("normalized.price_tick") == 4

        async with storage.pool.connection() as connection:
            raw_counts = await (
                await connection.execute(
                    """
                    SELECT instrument, count(*)
                    FROM raw_provider_events
                    GROUP BY instrument
                    ORDER BY instrument
                    """
                )
            ).fetchall()
            tick_counts = await (
                await connection.execute(
                    """
                    SELECT instrument, count(*)
                    FROM price_ticks
                    GROUP BY instrument
                    ORDER BY instrument
                    """
                )
            ).fetchall()
        assert {(str(row[0]), int(row[1])) for row in raw_counts} == {
            (instrument, 1) for instrument in SUPPORTED_INSTRUMENTS
        }
        assert {(str(row[0]), int(row[1])) for row in tick_counts} == {
            (instrument, 1) for instrument in SUPPORTED_INSTRUMENTS
        }

        for output in outputs.values():
            await storage.store_tick(output.tick)
        async with storage.pool.connection() as connection:
            idempotent_count = await (
                await connection.execute("SELECT count(*) FROM price_ticks")
            ).fetchone()
        assert idempotent_count == (4,)

        crossed = ProviderEnvelope(
            event_id="integration-crossed",
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
            state=AdapterState.DEGRADED,
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
            "normalized.price_tick",
            "integration-consumers",
            "consumer-1",
            count=10,
            block_ms=1,
        )
        assert len(messages) == 4
        stream_instruments = {json.loads(fields["event"])["instrument"] for _, fields in messages}
        assert stream_instruments == set(SUPPORTED_INSTRUMENTS)
        for message_id, _ in messages:
            await bus.acknowledge("normalized.price_tick", "integration-consumers", message_id)

        await bus.close()
        restarted_bus = RedisEventBus(settings.redis_url)
        assert await restarted_bus.ping()
        for instrument in SUPPORTED_INSTRUMENTS:
            assert await restarted_bus.redis.get(f"latest:quote:IC_MARKETS:{instrument}")
        await restarted_bus.close()
    finally:
        await storage.close()


def test_v01_and_v02_replay_fixtures() -> None:
    root = Path(__file__).resolve().parents[2]
    legacy = asyncio.run(
        replay_file(
            root / "adapters/ic_markets/fixtures/replay_bridge.jsonl",
            "max",
            False,
            False,
        )
    )
    assert legacy["total_raw_events"] == 4
    assert legacy["valid_ticks"] == 3
    mixed = asyncio.run(
        replay_file(
            root / "adapters/ic_markets/fixtures/replay_four_pair_mixed.jsonl",
            "max",
            False,
            False,
        )
    )
    assert mixed["total_raw_events"] == 8
    assert mixed["valid_ticks"] == 8
    assert all(
        mixed["pairs"][instrument]["normalized"] == 2 for instrument in SUPPORTED_INSTRUMENTS
    )
