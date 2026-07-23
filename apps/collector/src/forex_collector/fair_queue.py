from __future__ import annotations

import asyncio

from forex_contracts import SUPPORTED_INSTRUMENTS, SupportedInstrument


class FairInstrumentQueue[T]:
    """Bounded per-pair FIFO queues consumed in deterministic round-robin order."""

    def __init__(self, total_capacity: int) -> None:
        if total_capacity < len(SUPPORTED_INSTRUMENTS):
            raise ValueError("queue capacity must provide at least one slot per instrument")
        per_pair = max(1, total_capacity // len(SUPPORTED_INSTRUMENTS))
        self.queues: dict[SupportedInstrument, asyncio.Queue[T]] = {
            instrument: asyncio.Queue(maxsize=per_pair) for instrument in SUPPORTED_INSTRUMENTS
        }
        self.available = asyncio.Event()
        self.cursor = 0

    async def put(self, instrument: SupportedInstrument, item: T) -> None:
        await self.queues[instrument].put(item)
        self.available.set()

    async def get(self) -> tuple[SupportedInstrument, T]:
        while True:
            for offset in range(len(SUPPORTED_INSTRUMENTS)):
                index = (self.cursor + offset) % len(SUPPORTED_INSTRUMENTS)
                instrument = SUPPORTED_INSTRUMENTS[index]
                queue = self.queues[instrument]
                try:
                    item = queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                self.cursor = (index + 1) % len(SUPPORTED_INSTRUMENTS)
                if self.total_depth() == 0:
                    self.available.clear()
                return instrument, item
            self.available.clear()
            if self.total_depth() > 0:
                self.available.set()
                continue
            await self.available.wait()

    def task_done(self, instrument: SupportedInstrument) -> None:
        self.queues[instrument].task_done()

    async def join(self) -> None:
        await asyncio.gather(*(queue.join() for queue in self.queues.values()))

    def depth(self, instrument: SupportedInstrument) -> int:
        return self.queues[instrument].qsize()

    def total_depth(self) -> int:
        return sum(queue.qsize() for queue in self.queues.values())
