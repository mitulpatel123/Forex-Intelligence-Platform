import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient
from forex_collector.main import create_app
from forex_collector.settings import Settings
from storage import PostgresStorage


async def reset_storage(settings: Settings) -> None:
    storage = PostgresStorage(settings.database_url)
    await storage.open()
    try:
        await storage.migrate(Path(__file__).resolve().parents[2] / "migrations")
        await storage.reset_test_state()
    finally:
        await storage.close()


async def raw_rows(settings: Settings) -> list[tuple[str, str]]:
    storage = PostgresStorage(settings.database_url)
    await storage.open()
    try:
        async with storage.pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT raw_event_id, payload FROM raw_provider_events ORDER BY received_time"
                )
            ).fetchall()
            return [(str(row[0]), str(row[1])) for row in rows]
    finally:
        await storage.close()


def test_browser_ack_idempotency_heartbeat_and_server_redaction(tmp_path: Path) -> None:
    token = "t" * 48
    token_path = tmp_path / "bridge-token"
    token_path.write_text(token)
    token_path.chmod(0o600)
    settings = Settings(bridge_token_file=str(token_path))
    asyncio.run(reset_storage(settings))

    headers = {"X-Bridge-Token": token}
    with TestClient(create_app(settings)) as client:
        heartbeat = client.post(
            "/ingest/bridge-heartbeat",
            headers=headers,
            json={
                "connection_id": "browser-run-tab-1-frame-0",
                "session_id": "document-session-1",
                "observer_ready": True,
                "bridge_state": "waiting for EUR/USD",
                "outbox_pending": 1,
                "outbox_produced": 1,
                "outbox_acknowledged": 0,
                "outbox_retries": 0,
                "outbox_dropped": 0,
                "outbox_rejected": 0,
            },
        )
        assert heartbeat.status_code == 200
        health = client.get("/health/components").json()
        assert health["bridge"]["connected"] is True
        assert health["bridge"]["observer_ready"] is True
        assert health["components"]["adapter"] == "INITIALIZING"

        observed_at = datetime.now(UTC).isoformat()
        provider_body = {
            "event_id": "11111111-1111-4111-8111-111111111111",
            "connection_id": "browser-run-tab-1-frame-0",
            "session_id": "document-session-1",
            "received_at": observed_at,
            "semantics": "snapshot",
            "payload": {
                "instrument": "EURUSD",
                "bid": "1.13743",
                "ask": "1.13744",
                "provider_event_time": None,
                "observation_source": "visible_dom",
                "observation_level": "DISPLAY_QUOTE",
                "is_provider_tick": False,
            },
            "channel_metadata": {
                "observation_event_id": "11111111-1111-4111-8111-111111111111",
                "observation_level": "DISPLAY_QUOTE",
                "is_provider_tick": False,
            },
        }
        first = client.post("/ingest/provider", headers=headers, json=provider_body)
        duplicate = client.post("/ingest/provider", headers=headers, json=provider_body)
        assert first.status_code == 200
        assert first.json()["duplicate"] is False
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        receiving_health = client.get("/health/components").json()
        assert receiving_health["components"]["adapter"] == "CONNECTED"
        assert receiving_health["feed"]["status"] == "HEALTHY"

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

    rows = asyncio.run(raw_rows(settings))
    assert [row[0] for row in rows] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    discovery_payload = rows[1][1]
    assert "123456" not in discovery_payload
    assert "session-secret" not in discovery_payload
    assert "token-secret" not in discovery_payload

    async def display_provenance() -> tuple[str, str, bool] | None:
        storage = PostgresStorage(settings.database_url)
        await storage.open()
        try:
            async with storage.pool.connection() as connection:
                row = await (
                    await connection.execute(
                        """
                        SELECT source, observation_level, is_provider_tick
                        FROM price_ticks
                        WHERE raw_event_id = %s
                        """,
                        ("11111111-1111-4111-8111-111111111111",),
                    )
                ).fetchone()
                return (str(row[0]), str(row[1]), bool(row[2])) if row else None
        finally:
            await storage.close()

    assert asyncio.run(display_provenance()) == ("VISIBLE_DOM", "DISPLAY_QUOTE", False)
