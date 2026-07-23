from __future__ import annotations

import json
from typing import Any, Protocol

from redis.asyncio import Redis

STREAM_MAXLEN = 100_000


class EventModel(Protocol):
    event_id: str

    def model_dump_json(self) -> str: ...


class QuoteEventModel(EventModel, Protocol):
    @property
    def instrument(self) -> str: ...


class RedisEventBus:
    def __init__(self, url: str) -> None:
        self.redis = Redis.from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def publish(self, stream: str, event: EventModel, attempts: int = 1) -> str:
        payload = event.model_dump_json()
        return str(
            await self.redis.xadd(
                stream,
                {"event": payload, "event_id": event.event_id, "attempts": attempts},
                maxlen=STREAM_MAXLEN,
                approximate=True,
            )
        )

    async def set_latest_quote(self, event: QuoteEventModel) -> None:
        await self.redis.set(
            f"latest:quote:IC_MARKETS:{event.instrument}",
            event.model_dump_json(),
        )

    async def set_feed_health(self, instrument: str, value: dict[str, Any]) -> None:
        await self.redis.set(
            f"health:feed:IC_MARKETS:{instrument}",
            json.dumps(value, sort_keys=True, default=str),
        )

    async def ensure_group(self, stream: str, group: str) -> None:
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume(
        self, stream: str, group: str, consumer: str, count: int = 100, block_ms: int = 1000
    ) -> list[tuple[str, dict[str, Any]]]:
        response = await self.redis.xreadgroup(
            group, consumer, {stream: ">"}, count=count, block=block_ms
        )
        if not response:
            return []
        return [(message_id, fields) for _, messages in response for message_id, fields in messages]

    async def acknowledge(self, stream: str, group: str, message_id: str) -> None:
        await self.redis.xack(stream, group, message_id)

    async def dead_letter(self, source_stream: str, message: dict[str, Any], reason: str) -> None:
        await self.redis.xadd(
            f"{source_stream}.dead_letter",
            {"message": json.dumps(message, sort_keys=True), "reason": reason},
            maxlen=10_000,
            approximate=True,
        )

    async def reset_test_state(self) -> None:
        keys = [
            "raw.provider.ic_markets",
            "normalized.price_tick",
            "quality.events",
            "adapter.status",
            "raw.provider.ic_markets.dead_letter",
            *[
                f"{prefix}:IC_MARKETS:{instrument}"
                for prefix in ("latest:quote", "health:feed")
                for instrument in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD")
            ],
        ]
        await self.redis.delete(*keys)

    async def close(self) -> None:
        await self.redis.aclose()
