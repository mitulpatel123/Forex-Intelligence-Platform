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
from forex_contracts import SUPPORTED_INSTRUMENTS, SupportedInstrument
from ic_markets_adapter import IcMarketsAdapter

from forex_collector.fair_queue import FairInstrumentQueue
from forex_collector.pipeline import Pipeline

app = typer.Typer()

DISTRIBUTION: tuple[SupportedInstrument, ...] = (
    *("EURUSD" for _ in range(8)),
    *("GBPUSD" for _ in range(5)),
    *("USDJPY" for _ in range(4)),
    *("AUDUSD" for _ in range(3)),
)
BASE_PRICES = {
    "EURUSD": Decimal("1.08000"),
    "GBPUSD": Decimal("1.32000"),
    "USDJPY": Decimal("163.800"),
    "AUDUSD": Decimal("0.69000"),
}
PRICE_STEPS = {
    "EURUSD": Decimal("0.00001"),
    "GBPUSD": Decimal("0.00001"),
    "USDJPY": Decimal("0.001"),
    "AUDUSD": Decimal("0.00001"),
}


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * ratio))]


async def execute(rate: int, duration: int) -> dict[str, object]:
    pipeline = Pipeline(IcMarketsAdapter())
    count = rate * duration
    start_time = datetime.now(UTC)
    latencies = {instrument: [] for instrument in SUPPORTED_INSTRUMENTS}
    processed = {instrument: 0 for instrument in SUPPORTED_INSTRUMENTS}
    dropped = {instrument: 0 for instrument in SUPPORTED_INSTRUMENTS}
    sequences = {instrument: 0 for instrument in SUPPORTED_INSTRUMENTS}
    max_depth = {instrument: 0 for instrument in SUPPORTED_INSTRUMENTS}
    queue: FairInstrumentQueue[tuple[ProviderEnvelope, float]] = FairInstrumentQueue(10_000)

    async def worker() -> None:
        while True:
            instrument, (envelope, enqueued_at) = await queue.get()
            try:
                output = await pipeline.process(envelope)
                if output.tick is None:
                    dropped[instrument] += 1
                else:
                    processed[instrument] += 1
                latencies[instrument].append(perf_counter() - enqueued_at)
            finally:
                queue.task_done(instrument)

    worker_task = asyncio.create_task(worker())
    started = perf_counter()
    for index in range(count):
        instrument = DISTRIBUTION[index % len(DISTRIBUTION)]
        sequences[instrument] += 1
        sequence = sequences[instrument]
        price = BASE_PRICES[instrument] + Decimal(sequence % 10) * PRICE_STEPS[instrument]
        received = start_time + timedelta(microseconds=index)
        envelope = ProviderEnvelope(
            connection_id="mixed-load",
            session_id="mixed-load",
            received_at=received,
            semantics="snapshot",
            payload={
                "instrument": instrument,
                "provider_event_time": received.isoformat().replace("+00:00", "Z"),
                "sequence": sequence,
                "bid": str(price),
                "ask": str(price + PRICE_STEPS[instrument] * 2),
            },
        )
        try:
            await asyncio.wait_for(
                queue.put(instrument, (envelope, perf_counter())),
                timeout=max(0.001, 1 / rate),
            )
            max_depth[instrument] = max(max_depth[instrument], queue.depth(instrument))
        except TimeoutError:
            dropped[instrument] += 1
        target_elapsed = (index + 1) / rate
        current_elapsed = perf_counter() - started
        if current_elapsed < target_elapsed:
            await asyncio.sleep(target_elapsed - current_elapsed)
    await queue.join()
    worker_task.cancel()
    await asyncio.gather(worker_task, return_exceptions=True)
    elapsed = perf_counter() - started
    process = psutil.Process()
    pairs = {
        instrument: {
            "processed": processed[instrument],
            "dropped": dropped[instrument],
            "p50_latency_ms": round(
                statistics.median(latencies[instrument]) * 1000 if latencies[instrument] else 0,
                4,
            ),
            "p95_latency_ms": round(percentile(latencies[instrument], 0.95) * 1000, 4),
            "p99_latency_ms": round(percentile(latencies[instrument], 0.99) * 1000, 4),
            "max_queue_depth": max_depth[instrument],
        }
        for instrument in SUPPORTED_INSTRUMENTS
    }
    return {
        "input_rate": rate,
        "duration_seconds": duration,
        "processed_count": sum(processed.values()),
        "dropped_count": sum(dropped.values()),
        "distribution": "EURUSD=40%,GBPUSD=25%,USDJPY=20%,AUDUSD=15%",
        "fairness": {
            "scheduler": "per-pair FIFO with round-robin service",
            "all_pairs_processed": all(
                processed[instrument] > 0 for instrument in SUPPORTED_INSTRUMENTS
            ),
            "starved_pairs": [
                instrument for instrument in SUPPORTED_INSTRUMENTS if processed[instrument] == 0
            ],
        },
        "workload_qualification": (
            "deterministic local display-quote pipeline load; not provider-native HFT performance"
        ),
        "pairs": pairs,
        "peak_memory_bytes": process.memory_info().rss,
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
