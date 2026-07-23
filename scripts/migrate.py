import asyncio
from pathlib import Path

from forex_collector.settings import Settings
from storage import PostgresStorage


async def main() -> None:
    storage = PostgresStorage(Settings().database_url)
    await storage.open()
    try:
        await storage.migrate(Path(__file__).resolve().parents[1] / "migrations")
    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
