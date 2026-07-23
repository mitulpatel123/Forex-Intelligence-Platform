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
        "browser_observed_at": observed_at,
        "received_at": observed_at,
        "observation_sequence": 1,
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
                "browser_run_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "tab_id": 1,
                "frame_id": 0,
                "document_session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
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
            if instrument == "EURUSD":
                body["payload"] = {
                    **body["payload"],  # type: ignore[dict-item]
                    "provider_event_time": "2099-01-01T00:00:00Z",
                    "source": "PROVIDER_WIRE",
                    "observation_source": "provider_wire",
                    "observation_level": "PROVIDER_TICK",
                    "is_provider_tick": True,
                    "sequence": 999,
                }
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
                "browser_run_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "tab_id": 1,
                "frame_id": 0,
                "document_session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
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

    async def timestamp_evidence() -> list[tuple[object, ...]]:
        storage = PostgresStorage(settings.database_url)
        await storage.open()
        try:
            async with storage.pool.connection() as connection:
                return list(
                    await (
                        await connection.execute(
                            """
                            SELECT provider_event_time, received_time,
                                   browser_observed_at, collector_received_at,
                                   database_created_at, sequence,
                                   observation_sequence,
                                   browser_to_collector_delay_ms,
                                   collector_processing_delay_ms,
                                   total_local_pipeline_delay_ms
                            FROM price_ticks
                            ORDER BY instrument
                            """
                        )
                    ).fetchall()
                )
        finally:
            await storage.close()

    timestamps = asyncio.run(timestamp_evidence())
    assert len(timestamps) == 4
    assert all(row[0] is None for row in timestamps)
    assert all(row[1] == row[2] for row in timestamps)
    assert all(row[3] is not None and row[4] is not None for row in timestamps)
    assert all(row[5] is None and row[6] == 1 for row in timestamps)
    assert all(all(value is not None for value in row[7:]) for row in timestamps)


def test_active_source_lease_failover_and_untrusted_collector_time(
    tmp_path: Path,
) -> None:
    token = "u" * 48
    token_path = tmp_path / "bridge-token"
    token_path.write_text(token)
    settings = Settings(bridge_token_file=str(token_path))
    asyncio.run(reset_storage(settings))
    headers = {"X-Bridge-Token": token}
    observed_at = datetime.now(UTC).isoformat()

    def heartbeat(
        *,
        connection: str,
        session: str,
        run: str,
        tab: int,
        document: str,
        ready: bool,
    ) -> dict[str, object]:
        return {
            "connection_id": connection,
            "session_id": session,
            "browser_run_id": run,
            "tab_id": tab,
            "frame_id": 0,
            "document_session_id": document,
            "observer_ready": ready,
            "bridge_state": "receiving" if ready else "disconnected",
            "outbox_pending": 0,
            "outbox_produced": 0,
            "outbox_acknowledged": 0,
            "outbox_retries": 0,
            "outbox_dropped": 0,
            "outbox_rejected": 0,
            "pairs": heartbeat_pairs(observed_at),
        }

    with TestClient(create_app(settings)) as client:
        first_heartbeat = heartbeat(
            connection="browser-run-tab-1-frame-0",
            session="document-session-1",
            run="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            tab=1,
            document="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            ready=True,
        )
        second_heartbeat = heartbeat(
            connection="browser-run-tab-2-frame-0",
            session="document-session-2",
            run="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            tab=2,
            document="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            ready=True,
        )
        assert (
            client.post(
                "/ingest/bridge-heartbeat", headers=headers, json=first_heartbeat
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/ingest/bridge-heartbeat", headers=headers, json=second_heartbeat
            ).status_code
            == 200
        )
        health = client.get("/health/components").json()
        assert health["pairs"]["EURUSD"]["source_status"] == "MULTIPLE_SOURCES"
        assert health["pairs"]["EURUSD"]["active_source"]["tab_id"] == 1

        standby = provider_body("EURUSD", "standby-event-0001", observed_at)
        standby.update(
            {
                "browser_run_id": second_heartbeat["browser_run_id"],
                "tab_id": 2,
                "document_session_id": second_heartbeat["document_session_id"],
                "connection_id": second_heartbeat["connection_id"],
                "session_id": second_heartbeat["session_id"],
            }
        )
        suppressed = client.post("/ingest/provider", headers=headers, json=standby)
        assert suppressed.status_code == 200
        assert suppressed.json()["reason"] == "STANDBY_SOURCE"

        malicious = provider_body("EURUSD", "malicious-time-0001", observed_at)
        malicious["collector_received_at"] = "2099-01-01T00:00:00Z"
        assert client.post("/ingest/provider", headers=headers, json=malicious).status_code == 422

        first_heartbeat["observer_ready"] = False
        assert (
            client.post(
                "/ingest/bridge-heartbeat", headers=headers, json=first_heartbeat
            ).status_code
            == 200
        )
        standby["event_id"] = "failover-event-0002"
        standby["observation_sequence"] = 2
        failover = client.post("/ingest/provider", headers=headers, json=standby)
        assert failover.status_code == 200
        assert failover.json()["valid_ticks"] == 1

        old_active = provider_body("EURUSD", "old-active-event-0002", observed_at)
        old_active["observation_sequence"] = 2
        old_return = client.post("/ingest/provider", headers=headers, json=old_active)
        assert old_return.status_code == 200
        assert old_return.json()["reason"] == "STANDBY_SOURCE"
