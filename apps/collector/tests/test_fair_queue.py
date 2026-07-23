from __future__ import annotations

import asyncio

import pytest
from forex_collector.fair_queue import FairInstrumentQueue


@pytest.mark.asyncio
async def test_round_robin_fairness_and_per_pair_fifo() -> None:
    queue: FairInstrumentQueue[str] = FairInstrumentQueue(16)
    for value in ("eur-1", "eur-2", "eur-3"):
        await queue.put("EURUSD", value)
    await queue.put("GBPUSD", "gbp-1")
    await queue.put("USDJPY", "jpy-1")
    await queue.put("AUDUSD", "aud-1")
    received: list[str] = []
    for _ in range(6):
        instrument, value = await queue.get()
        received.append(value)
        queue.task_done(instrument)
    await queue.join()
    assert received == ["eur-1", "gbp-1", "jpy-1", "aud-1", "eur-2", "eur-3"]


@pytest.mark.asyncio
async def test_queue_capacity_is_isolated_per_pair() -> None:
    queue: FairInstrumentQueue[str] = FairInstrumentQueue(4)
    await queue.put("EURUSD", "eur")
    blocked = asyncio.create_task(queue.put("EURUSD", "eur-blocked"))
    await asyncio.sleep(0)
    assert not blocked.done()
    await queue.put("AUDUSD", "aud")
    instrument, value = await queue.get()
    assert (instrument, value) == ("EURUSD", "eur")
    queue.task_done(instrument)
    await asyncio.wait_for(blocked, timeout=0.1)
    assert queue.depth("EURUSD") == 1
    assert queue.depth("AUDUSD") == 1


@pytest.mark.asyncio
async def test_graceful_drain_waits_for_every_pair() -> None:
    queue: FairInstrumentQueue[str] = FairInstrumentQueue(8)
    for instrument in ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD"):
        await queue.put(instrument, instrument)
    join = asyncio.create_task(queue.join())
    await asyncio.sleep(0)
    assert not join.done()
    for _ in range(4):
        instrument, _ = await queue.get()
        queue.task_done(instrument)
    await asyncio.wait_for(join, timeout=0.1)
