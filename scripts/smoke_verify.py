from __future__ import annotations

import asyncio

from forex_collector.settings import Settings
from forex_contracts import SUPPORTED_INSTRUMENTS
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis


async def main() -> None:
    settings = Settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    database = AsyncConnectionPool(settings.database_url, min_size=1, max_size=1, open=False)
    await database.open()
    try:
        for instrument in SUPPORTED_INSTRUMENTS:
            value = await redis.get(f"latest:quote:IC_MARKETS:{instrument}")
            if value is None or "PRICE_TICK" not in value:
                raise RuntimeError(f"missing latest display quote for {instrument}")
        async with database.connection() as connection:
            instruments = await (
                await connection.execute("SELECT count(DISTINCT instrument) FROM price_ticks")
            ).fetchone()
            raw = await (
                await connection.execute("SELECT count(*) FROM raw_provider_events")
            ).fetchone()
        if instruments is None or int(instruments[0]) != len(SUPPORTED_INSTRUMENTS):
            raise RuntimeError("database does not contain all supported instruments")
        if raw is None or int(raw[0]) < 1:
            raise RuntimeError("database does not contain raw provider events")
    finally:
        await redis.aclose()
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())
