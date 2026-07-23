from __future__ import annotations

import asyncio
import json
import statistics
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Annotated

import psutil
import typer
from adapter_sdk import ProviderEnvelope
from ic_markets_adapter import IcMarketsAdapter

from forex_collector.pipeline import Pipeline

app = typer.Typer()


async def execute(rate: int, duration: int) -> dict[str, int | float]:
    adapter = IcMarketsAdapter()
    pipeline = Pipeline(adapter)
    count = rate * duration
    start_time = datetime.now(UTC)
    latencies: list[float] = []
    dropped = 0
    started = perf_counter()
    for index in range(count):
        tick_started = perf_counter()
        price = Decimal("1.08000") + Decimal(index % 10) / Decimal("100000")
        received = start_time + timedelta(microseconds=index)
        envelope = ProviderEnvelope(
            connection_id="load",
            session_id="load",
            received_at=received,
            semantics="snapshot",
            payload={
                "instrument": "EURUSD",
                "provider_event_time": received.isoformat().replace("+00:00", "Z"),
                "sequence": index,
                "bid": str(price),
                "ask": str(price + Decimal("0.00002")),
            },
        )
        output = await pipeline.process(envelope)
        if output.tick is None:
            dropped += 1
        latencies.append(perf_counter() - tick_started)
        target_elapsed = (index + 1) / rate
        current_elapsed = perf_counter() - started
        if current_elapsed < target_elapsed:
            await asyncio.sleep(target_elapsed - current_elapsed)
    elapsed = perf_counter() - started
    ordered = sorted(latencies)

    def percentile(ratio: float) -> float:
        return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]

    process = psutil.Process()
    return {
        "input_rate": rate,
        "duration_seconds": duration,
        "processed_count": count - dropped,
        "dropped_count": dropped,
        "p50_latency_ms": round(statistics.median(latencies) * 1000, 4),
        "p95_latency_ms": round(percentile(0.95) * 1000, 4),
        "p99_latency_ms": round(percentile(0.99) * 1000, 4),
        "peak_memory_bytes": process.memory_info().rss,
        "max_queue_depth": 0,
        "actual_elapsed_seconds": round(elapsed, 4),
    }


@app.command()
def main(
    rate: Annotated[int, typer.Option(min=1)] = 1000,
    duration: Annotated[int, typer.Option(min=1)] = 5,
) -> None:
    typer.echo(json.dumps(asyncio.run(execute(rate, duration)), sort_keys=True))


if __name__ == "__main__":
    app()
