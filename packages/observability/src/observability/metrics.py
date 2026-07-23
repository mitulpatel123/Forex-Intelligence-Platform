from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


class Metrics:
    adapter_connected = Gauge("adapter_connected", "IC Markets adapter connected")
    bridge_connected = Gauge("bridge_connected", "Browser bridge heartbeat is fresh")
    observer_ready = Gauge("observer_ready", "At least one browser observer is ready")
    display_observations_total = Counter(
        "display_observations_total",
        "Unique browser display observations",
        ["instrument"],
    )
    browser_outbox_produced_total = Gauge(
        "browser_outbox_produced_total",
        "Browser observations produced",
        ["instrument"],
    )
    browser_outbox_pending = Gauge(
        "browser_outbox_pending",
        "Browser events awaiting ack",
        ["instrument"],
    )
    browser_outbox_dropped_total = Gauge(
        "browser_outbox_dropped_total",
        "Browser events explicitly dropped",
        ["instrument"],
    )
    browser_outbox_retries_total = Gauge(
        "browser_outbox_retries_total",
        "Browser delivery retry attempts",
        ["instrument"],
    )
    browser_outbox_acknowledged_total = Gauge(
        "browser_outbox_acknowledged_total",
        "Browser events acknowledged by collector",
        ["instrument"],
    )
    browser_outbox_rejected_total = Gauge(
        "browser_outbox_rejected_total",
        "Browser observations rejected",
        ["instrument"],
    )
    adapter_reconnect_total = Counter("adapter_reconnect_total", "Adapter reconnects")
    provider_messages_total = Counter("provider_messages_total", "Provider messages")
    provider_message_bytes_total = Counter("provider_message_bytes_total", "Provider message bytes")
    raw_events_total = Counter("raw_events_total", "Accepted raw events", ["instrument"])
    normalized_ticks_total = Counter(
        "normalized_ticks_total", "Published normalized ticks", ["instrument"]
    )
    invalid_events_total = Counter("invalid_events_total", "Invalid events", ["instrument"])
    duplicate_events_total = Counter("duplicate_events_total", "Duplicate events", ["instrument"])
    out_of_order_events_total = Counter(
        "out_of_order_events_total", "Out-of-order events", ["instrument"]
    )
    stale_events_total = Counter("stale_events_total", "Stale events", ["instrument"])
    events_by_quality_total = Counter("events_by_quality_total", "Events by quality", ["quality"])
    last_valid_tick_age_seconds = Gauge(
        "last_valid_tick_age_seconds", "Age of the last valid tick", ["instrument"]
    )
    latest_display_bid = Gauge("latest_display_bid", "Latest displayed bid", ["instrument"])
    latest_display_ask = Gauge("latest_display_ask", "Latest displayed ask", ["instrument"])
    latest_display_spread_pips = Gauge(
        "latest_display_spread_pips", "Latest displayed spread in pips", ["instrument"]
    )
    ingest_latency_seconds = Histogram("ingest_latency_seconds", "Provider to receive latency")
    normalization_latency_seconds = Histogram(
        "normalization_latency_seconds", "Normalization latency", ["instrument"]
    )
    redis_publish_latency_seconds = Histogram(
        "redis_publish_latency_seconds", "Redis publish latency", ["instrument"]
    )
    timescale_write_latency_seconds = Histogram(
        "timescale_write_latency_seconds", "Timescale write latency", ["instrument"]
    )
    event_bus_consumer_lag = Gauge("event_bus_consumer_lag", "Redis consumer lag")
    collector_queue_depth = Gauge("collector_queue_depth", "Collector queue depth", ["instrument"])
    collector_dropped_events_total = Counter(
        "collector_dropped_events_total", "Dropped events", ["instrument"]
    )
    collector_process_cpu_percent = Gauge("collector_process_cpu_percent", "Collector CPU percent")
    collector_process_memory_bytes = Gauge(
        "collector_process_memory_bytes", "Collector resident memory bytes"
    )


METRICS = Metrics()
