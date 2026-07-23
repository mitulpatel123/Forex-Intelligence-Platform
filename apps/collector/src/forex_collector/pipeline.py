from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from adapter_sdk import ProviderEnvelope
from adapter_sdk.interface import AdapterOutput
from event_bus import RedisEventBus
from forex_contracts import QualityStatus
from ic_markets_adapter import IcMarketsAdapter
from observability import METRICS
from storage import PostgresStorage


class Pipeline:
    def __init__(
        self,
        adapter: IcMarketsAdapter,
        bus: RedisEventBus | None = None,
        storage: PostgresStorage | None = None,
    ) -> None:
        self.adapter = adapter
        self.bus = bus
        self.storage = storage

    async def process(self, envelope: ProviderEnvelope) -> AdapterOutput:
        started = perf_counter()
        METRICS.provider_messages_total.inc()
        METRICS.provider_message_bytes_total.inc(len(str(envelope.payload).encode()))
        output = self.adapter.process(envelope)

        if self.storage:
            storage_started = perf_counter()
            await self.storage.store_raw(output.raw_event)
            METRICS.timescale_write_latency_seconds.observe(perf_counter() - storage_started)
        if self.bus:
            redis_started = perf_counter()
            await self.bus.publish("raw.provider.ic_markets", output.raw_event)
            METRICS.redis_publish_latency_seconds.observe(perf_counter() - redis_started)
        METRICS.raw_events_total.inc()

        for quality in output.quality_events:
            METRICS.events_by_quality_total.labels(quality.classification).inc()
            if quality.classification == QualityStatus.DUPLICATE:
                METRICS.duplicate_events_total.inc()
            elif quality.classification == QualityStatus.OUT_OF_ORDER:
                METRICS.out_of_order_events_total.inc()
            elif quality.classification == QualityStatus.STALE:
                METRICS.stale_events_total.inc()
            elif quality.classification in {QualityStatus.BAD, QualityStatus.UNPARSEABLE}:
                METRICS.invalid_events_total.inc()
            if self.storage:
                await self.storage.store_quality(quality)
            if self.bus:
                await self.bus.publish("quality.events", quality)

        if output.tick:
            if self.storage:
                await self.storage.store_tick(output.tick)
            if self.bus:
                await self.bus.publish("normalized.price_tick", output.tick)
                await self.bus.set_latest_quote(output.tick)
            METRICS.normalized_ticks_total.inc()
            METRICS.events_by_quality_total.labels(output.tick.quality_status).inc()
            if output.tick.provider_event_time:
                latency = (
                    output.tick.received_at.astimezone(UTC)
                    - output.tick.provider_event_time.astimezone(UTC)
                ).total_seconds()
                METRICS.ingest_latency_seconds.observe(max(0, latency))
            METRICS.last_valid_tick_age_seconds.set(
                max(0, (datetime.now(UTC) - output.tick.received_at).total_seconds())
            )
        METRICS.normalization_latency_seconds.observe(perf_counter() - started)
        return output
