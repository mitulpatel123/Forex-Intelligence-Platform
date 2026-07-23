from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any

import typer
from adapter_sdk import ProviderEnvelope
from event_bus import RedisEventBus
from forex_contracts import SUPPORTED_INSTRUMENTS, is_supported_instrument
from ic_markets_adapter import IcMarketsAdapter
from storage import PostgresStorage

from forex_collector.pipeline import Pipeline
from forex_collector.settings import Settings

app = typer.Typer(help="Replay sanitized discovery-bridge fixtures deterministically.")


async def replay_file(path: Path, speed: str, publish: bool, reset: bool) -> dict[str, Any]:
    settings = Settings()
    bus = RedisEventBus(settings.redis_url) if publish else None
    storage = PostgresStorage(settings.database_url) if publish else None
    if storage:
        await storage.open()
    if reset:
        if not publish or not bus or not storage:
            raise ValueError("--reset requires --publish")
        await bus.reset_test_state()
        await storage.reset_test_state()
    pipeline = Pipeline(IcMarketsAdapter(), bus, storage)
    records = [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    counters: dict[str, Any] = {
        "total_raw_events": 0,
        "valid_ticks": 0,
        "invalid_events": 0,
        "duplicates": 0,
        "out_of_order_events": 0,
    }
    pairs: dict[str, dict[str, int | float]] = {
        instrument: {
            "raw": 0,
            "normalized": 0,
            "warnings": 0,
            "invalid": 0,
            "duplicates": 0,
            "out_of_order": 0,
        }
        for instrument in SUPPORTED_INSTRUMENTS
    }
    previous_received: datetime | None = None
    started = perf_counter()
    for record in records:
        received = datetime.fromisoformat(record["received_at"].replace("Z", "+00:00"))
        if previous_received is not None:
            delay = max(0.0, (received - previous_received).total_seconds())
            if speed == "realtime":
                await asyncio.sleep(delay)
            elif speed.startswith("x"):
                await asyncio.sleep(delay / float(speed[1:]))
            elif speed == "step":
                typer.echo("Press Enter for next event.")
                await asyncio.to_thread(input)
        envelope = ProviderEnvelope(
            event_id=record.get("event_id"),
            connection_id=record["connection_id"],
            session_id=record["session_id"],
            document_session_id=record.get("document_session_id"),
            observation_sequence=record.get("observation_sequence"),
            browser_observed_at=(
                datetime.fromisoformat(record["browser_observed_at"].replace("Z", "+00:00"))
                if record.get("browser_observed_at")
                else None
            ),
            collector_received_at=(
                datetime.fromisoformat(record["collector_received_at"].replace("Z", "+00:00"))
                if record.get("collector_received_at")
                else None
            ),
            received_at=received,
            payload=record["payload"],
            semantics=record["semantics"],
            channel_metadata={"fixture": path.name},
        )
        if publish:
            output = await pipeline.process(envelope)
        else:
            output = pipeline.adapter.process(envelope)
        valid = 1 if output.tick else 0
        invalid = sum(
            quality.classification in {"BAD", "UNPARSEABLE"} for quality in output.quality_events
        )
        counters["total_raw_events"] += 1
        counters["valid_ticks"] += valid
        counters["invalid_events"] += invalid
        counters["duplicates"] += sum(
            quality.classification == "DUPLICATE" for quality in output.quality_events
        )
        counters["out_of_order_events"] += sum(
            quality.classification == "OUT_OF_ORDER" for quality in output.quality_events
        )
        instrument = record["payload"].get("instrument")
        if is_supported_instrument(instrument):
            pair = pairs[instrument]
            pair["raw"] += 1
            pair["normalized"] += valid
            pair["warnings"] += sum(
                quality.classification == "WARNING" for quality in output.quality_events
            )
            pair["invalid"] += sum(
                quality.classification in {"BAD", "UNPARSEABLE"}
                for quality in output.quality_events
            )
            pair["duplicates"] += sum(
                quality.classification == "DUPLICATE" for quality in output.quality_events
            )
            pair["out_of_order"] += sum(
                quality.classification == "OUT_OF_ORDER" for quality in output.quality_events
            )
        previous_received = received
    counters["elapsed_seconds"] = round(perf_counter() - started, 6)
    counters["pairs"] = pairs
    if bus:
        await bus.close()
    if storage:
        await storage.close()
    return counters


@app.command()
def run(
    fixture: Annotated[
        Path, typer.Argument(exists=True, readable=True, help="Sanitized JSONL fixture")
    ],
    speed: Annotated[str, typer.Option(help="max, realtime, step, or xN")] = "max",
    publish: Annotated[bool, typer.Option(help="Publish to Redis and TimescaleDB")] = False,
    reset: Annotated[bool, typer.Option(help="Reset only test pipeline state first")] = False,
) -> None:
    if speed not in {"max", "realtime", "step"} and not speed.startswith("x"):
        raise typer.BadParameter("speed must be max, realtime, step, or xN")
    result = asyncio.run(replay_file(fixture, speed, publish, reset))
    typer.echo(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    app()
