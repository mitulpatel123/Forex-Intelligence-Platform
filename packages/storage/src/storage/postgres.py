from __future__ import annotations

import json
from pathlib import Path

from forex_contracts import AdapterStatus, DataQualityEvent, PriceTick, RawProviderEvent
from psycopg import sql
from psycopg_pool import AsyncConnectionPool


class PostgresStorage:
    def __init__(self, url: str) -> None:
        self.pool = AsyncConnectionPool(url, min_size=1, max_size=5, open=False)

    async def open(self) -> None:
        await self.pool.open()
        await self.pool.wait()

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        async with self.pool.connection() as connection:
            return bool(await (await connection.execute("SELECT true")).fetchone())

    async def migrate(self, directory: Path) -> None:
        async with self.pool.connection() as connection:
            for migration in sorted(directory.glob("*.sql")):
                # Migration files are trusted repository assets, not runtime input.
                await connection.execute(
                    sql.SQL(migration.read_text())  # pyright: ignore[reportArgumentType]
                )
            await connection.commit()

    async def store_raw(self, event: RawProviderEvent) -> None:
        payload_json = (
            json.dumps(event.payload, sort_keys=True)
            if isinstance(event.payload, dict)
            else event.payload
        )
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO raw_provider_events (
                  raw_event_id, provider, adapter_instance, connection_id, session_id,
                  instrument, received_time, provider_time, payload_content_type,
                  payload, content_hash, redaction_status, metadata, created_time
                ) VALUES (
                  %(id)s, %(provider)s, %(adapter)s, %(connection)s, %(session)s,
                  %(instrument)s, %(received)s, %(provider_time)s, %(content_type)s,
                  %(payload)s, %(hash)s, %(redaction)s, %(metadata)s::jsonb, now()
                ) ON CONFLICT (raw_event_id, received_time) DO NOTHING
                """,
                {
                    "id": event.event_id,
                    "provider": event.provider,
                    "adapter": event.adapter_instance_id,
                    "connection": event.connection_id,
                    "session": event.session_id,
                    "instrument": event.instrument,
                    "received": event.received_at,
                    "provider_time": event.provider_event_time,
                    "content_type": event.payload_content_type,
                    "payload": payload_json,
                    "hash": event.content_hash,
                    "redaction": event.redaction_status,
                    "metadata": json.dumps(event.channel_metadata),
                },
            )
            await connection.commit()

    async def has_raw(self, event_id: str) -> bool:
        async with self.pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT 1 FROM raw_provider_events WHERE raw_event_id = %s LIMIT 1",
                    (event_id,),
                )
            ).fetchone()
            return row is not None

    async def store_tick(self, event: PriceTick) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO price_ticks (
                  event_id, schema_version, provider, adapter_instance, instrument,
                  base_currency, quote_currency, source, observation_level, is_provider_tick,
                  bid, ask, mid, spread, spread_pips, pip_size, provider_event_time,
                  received_time, normalized_time, sequence, snapshot, changed_fields,
                  quality_status, quality_flags, raw_event_id, trace_id
                ) VALUES (
                  %(event_id)s, %(schema_version)s, %(provider)s, %(adapter)s, %(instrument)s,
                  %(base_currency)s, %(quote_currency)s,
                  %(source)s, %(observation_level)s, %(is_provider_tick)s,
                  %(bid)s, %(ask)s, %(mid)s, %(spread)s, %(spread_pips)s, %(pip_size)s,
                  %(provider_time)s, %(received)s, %(normalized)s, %(sequence)s, %(snapshot)s,
                  %(changed)s, %(quality_status)s, %(quality_flags)s, %(raw_event_id)s,
                  %(trace_id)s
                ) ON CONFLICT (event_id, received_time) DO NOTHING
                """,
                {
                    "event_id": event.event_id,
                    "schema_version": event.schema_version,
                    "provider": event.provider,
                    "adapter": event.adapter_instance_id,
                    "instrument": event.instrument,
                    "base_currency": event.base_currency,
                    "quote_currency": event.quote_currency,
                    "source": event.source,
                    "observation_level": event.observation_level,
                    "is_provider_tick": event.is_provider_tick,
                    "bid": event.bid,
                    "ask": event.ask,
                    "mid": event.mid,
                    "spread": event.spread,
                    "spread_pips": event.spread_pips,
                    "pip_size": event.pip_size,
                    "provider_time": event.provider_event_time,
                    "received": event.received_at,
                    "normalized": event.normalized_at,
                    "sequence": event.sequence,
                    "snapshot": event.is_snapshot,
                    "changed": event.changed_fields,
                    "quality_status": event.quality_status,
                    "quality_flags": event.quality_flags,
                    "raw_event_id": event.raw_event_id,
                    "trace_id": event.trace_id,
                },
            )
            await connection.commit()

    async def store_quality(self, event: DataQualityEvent) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO data_quality_events (
                  quality_event_id, related_event_id, provider, instrument, severity,
                  rule_id, classification, action, details, timestamp
                ) VALUES (
                  %(id)s, %(related)s, %(provider)s, %(instrument)s, %(severity)s,
                  %(rule)s, %(classification)s, %(action)s, %(details)s::jsonb, %(timestamp)s
                ) ON CONFLICT (quality_event_id, timestamp) DO NOTHING
                """,
                {
                    "id": event.event_id,
                    "related": event.related_event_id,
                    "provider": event.provider,
                    "instrument": event.instrument,
                    "severity": event.severity,
                    "rule": event.rule_id,
                    "classification": event.classification,
                    "action": event.action_taken,
                    "details": json.dumps(event.details),
                    "timestamp": event.timestamp,
                },
            )
            await connection.commit()

    async def store_heartbeat(self, event: AdapterStatus) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO adapter_heartbeats (
                  adapter_instance, adapter_state, last_provider_message, last_valid_tick,
                  reconnect_count, error_summary, timestamp
                ) VALUES (
                  %(instance)s, %(state)s, %(last_message)s, %(last_tick)s,
                  %(reconnect)s, %(error)s, %(timestamp)s
                ) ON CONFLICT (adapter_instance, timestamp) DO NOTHING
                """,
                {
                    "instance": event.instance_id,
                    "state": event.state,
                    "last_message": event.last_message_time,
                    "last_tick": event.last_valid_tick_time,
                    "reconnect": event.reconnect_count,
                    "error": event.summary,
                    "timestamp": event.timestamp,
                },
            )
            await connection.commit()

    async def reset_test_state(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(
                "TRUNCATE raw_provider_events, price_ticks, data_quality_events, adapter_heartbeats"
            )
            await connection.commit()
