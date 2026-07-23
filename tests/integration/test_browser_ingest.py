import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from forex_collector.main import create_app
from forex_collector.settings import Settings
from forex_contracts import SUPPORTED_INSTRUMENTS
from storage import PostgresStorage

QUOTES = {
    "EURUSD": ("1.13743", "1.13744"),
    "GBPUSD": ("1.33155", "1.33157"),
    "USDJPY": ("163.832", "163.833"),
    "AUDUSD": ("0.69689", "0.69690"),
}


async def reset_storage(settings: Settings) -> None:
    storage = PostgresStorage(settings.database_url)
    await storage.open()
    try:
        await storage.migrate(Path(__file__).resolve().parents[2] / "migrations")
        await storage.reset_test_state()
    finally:
        await storage.close()


async def rows(settings: Settings) -> tuple[list[tuple[str, str, str | None]], list[str]]:
    storage = PostgresStorage(settings.database_url)
    await storage.open()
    try:
        async with storage.pool.connection() as connection:
            raw = await (
                await connection.execute(
                    """
                    SELECT raw_event_id, payload, instrument
                    FROM raw_provider_events
                    ORDER BY received_time, raw_event_id
                    """
                )
            ).fetchall()
            ticks = await (
                await connection.execute("SELECT instrument FROM price_ticks ORDER BY instrument")
            ).fetchall()
            return (
                [(str(row[0]), str(row[1]), str(row[2]) if row[2] else None) for row in raw],
                [str(row[0]) for row in ticks],
            )
    finally:
        await storage.close()


def heartbeat_pairs(
    observed_at: str,
    *,
    stale: str | None = None,
) -> dict[str, dict[str, object]]:
    return {
        instrument: {
            "target_status": "STALE" if instrument == stale else "READY",
            "last_observation_time": observed_at,
            "outbox_pending": 0,
            "outbox_produced": 1,
            "outbox_acknowledged": 1,
            "outbox_retries": 0,
            "outbox_dropped": 0,
            "outbox_rejected": 0,
        }
        for instrument in SUPPORTED_INSTRUMENTS
    }


def provider_body(instrument: str, event_id: str, observed_at: str) -> dict[str, object]:
    bid, ask = QUOTES[instrument]
    return {
        "event_id": event_id,
        "instrument": instrument,
        "browser_run_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "tab_id": 1,
        "frame_id": 0,
        "document_session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "connection_id": "browser-run-tab-1-frame-0",
        "session_id": "document-session-1",
        "received_at": observed_at,
        "semantics": "snapshot",
        "payload": {
            "instrument": instrument,
            "bid": bid,
            "ask": ask,
            "provider_event_time": None,
            "observation_source": "visible_dom",
            "observation_level": "DISPLAY_QUOTE",
            "is_provider_tick": False,
        },
        "channel_metadata": {
            "observation_event_id": event_id,
            "observation_level": "DISPLAY_QUOTE",
            "is_provider_tick": False,
        },
    }


def test_four_pair_browser_idempotency_health_isolation_and_redaction(
    tmp_path: Path,
) -> None:
    token = "t" * 48
    token_path = tmp_path / "bridge-token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    settings = Settings(bridge_token_file=str(token_path))
    asyncio.run(reset_storage(settings))

    headers = {"X-Bridge-Token": token}
    observed_at = datetime.now(UTC).isoformat()
    event_ids = {
        instrument: f"11111111-1111-4111-8111-11111111111{index}"
        for index, instrument in enumerate(SUPPORTED_INSTRUMENTS, start=1)
    }
    with TestClient(create_app(settings)) as client:
        heartbeat = client.post(
            "/ingest/bridge-heartbeat",
            headers=headers,
            json={
                "connection_id": "browser-run-tab-1-frame-0",
                "session_id": "document-session-1",
                "observer_ready": True,
                "bridge_state": "receiving",
                "outbox_pending": 0,
                "outbox_produced": 4,
                "outbox_acknowledged": 4,
                "outbox_retries": 0,
                "outbox_dropped": 0,
                "outbox_rejected": 0,
                "pairs": heartbeat_pairs(observed_at),
            },
        )
        assert heartbeat.status_code == 200

        for instrument in SUPPORTED_INSTRUMENTS:
            body = provider_body(instrument, event_ids[instrument], observed_at)
            first = client.post("/ingest/provider", headers=headers, json=body)
            duplicate = client.post("/ingest/provider", headers=headers, json=body)
            assert first.status_code == 200
            assert first.json() == {
                "accepted": True,
                "duplicate": False,
                "event_id": event_ids[instrument],
                "instrument": instrument,
                "valid_ticks": 1,
                "quality_events": 1,
            }
            assert duplicate.status_code == 200
            assert duplicate.json()["duplicate"] is True

        health = client.get("/health/components").json()
        assert health["components"]["adapter"] == "CONNECTED"
        assert set(health["pairs"]) == set(SUPPORTED_INSTRUMENTS)
        assert all(pair["status"] == "HEALTHY" for pair in health["pairs"].values())

        isolated = client.post(
            "/ingest/bridge-heartbeat",
            headers=headers,
            json={
                "connection_id": "browser-run-tab-1-frame-0",
                "session_id": "document-session-1",
                "observer_ready": True,
                "bridge_state": "receiving",
                "outbox_pending": 0,
                "outbox_produced": 4,
                "outbox_acknowledged": 4,
                "outbox_retries": 0,
                "outbox_dropped": 0,
                "outbox_rejected": 0,
                "pairs": heartbeat_pairs(observed_at, stale="GBPUSD"),
            },
        )
        assert isolated.status_code == 200
        degraded = client.get("/health/components").json()
        assert degraded["components"]["adapter"] == "DEGRADED"
        assert degraded["pairs"]["GBPUSD"]["status"] == "STALE"
        assert all(
            degraded["pairs"][instrument]["status"] == "HEALTHY"
            for instrument in ("EURUSD", "USDJPY", "AUDUSD")
        )

        discovery = client.post(
            "/ingest/discovery",
            headers=headers,
            json={
                "event_id": "22222222-2222-4222-8222-222222222222",
                "connection_id": "browser-run-tab-1-frame-0",
                "session_id": "document-session-1",
                "frame": {
                    "frameType": "websocket-text",
                    "payload": json.dumps(
                        {
                            "account": 123456,
                            "sessionId": "session-secret",
                            "accessToken": "token-secret",
                            "symbol": "EURUSD",
                        }
                    ),
                },
            },
        )
        assert discovery.status_code == 200

    raw_rows, tick_instruments = asyncio.run(rows(settings))
    assert len(raw_rows) == 5
    assert tick_instruments == sorted(SUPPORTED_INSTRUMENTS)
    for instrument, event_id in event_ids.items():
        assert len([row for row in raw_rows if row[0] == event_id]) == 1
        assert len([row for row in raw_rows if row[2] == instrument]) == 1
    discovery_payload = next(row[1] for row in raw_rows if row[0].startswith("22222222"))
    assert "123456" not in discovery_payload
    assert "session-secret" not in discovery_payload
    assert "token-secret" not in discovery_payload

    async def display_provenance() -> list[tuple[str, str, bool, str, str, str]]:
        storage = PostgresStorage(settings.database_url)
        await storage.open()
        try:
            async with storage.pool.connection() as connection:
                provenance = await (
                    await connection.execute(
                        """
                        SELECT source, observation_level, is_provider_tick, instrument,
                               base_currency, quote_currency
                        FROM price_ticks
                        ORDER BY instrument
                        """
                    )
                ).fetchall()
                return [
                    (
                        str(row[0]),
                        str(row[1]),
                        bool(row[2]),
                        str(row[3]),
                        str(row[4]),
                        str(row[5]),
                    )
                    for row in provenance
                ]
        finally:
            await storage.close()

    display = asyncio.run(display_provenance())
    assert display
    assert all(row[:3] == ("VISIBLE_DOM", "DISPLAY_QUOTE", False) for row in display)
    assert {row[3:] for row in display} == {
        ("EURUSD", "EUR", "USD"),
        ("GBPUSD", "GBP", "USD"),
        ("USDJPY", "USD", "JPY"),
        ("AUDUSD", "AUD", "USD"),
    }
