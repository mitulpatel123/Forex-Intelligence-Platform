# Architecture

```text
IC wrapper + MetaTrader iframe
  -> four visible Market Watch rows
  -> MV3 exact-header DOM observer
  -> persistent bounded per-pair outbox
  -> authenticated loopback collector
  -> bounded per-pair FIFO queues + round-robin scheduler
  -> immutable RAW_PROVIDER_EVENT
  -> registry-backed IC Markets adapter
  -> PRICE_TICK v0.2 + DATA_QUALITY_EVENT
  -> Redis Streams/four latest keys + TimescaleDB
  -> per-pair Prometheus metrics + provisioned Grafana dashboard
```

`packages/contracts/instrument_specs.json` is the single source of truth for
symbols, currencies, pip sizes, display precision, plausibility bounds, and warning
thresholds. A deterministic generator creates the Python and TypeScript artifacts;
CI rejects drift.

The browser observes `EURUSD`, `GBPUSD`, `USDJPY`, and `AUDUSD` independently.
Discovery scans at most 32 tables and 512 rows, maps exact Symbol/Bid/Ask headers,
ignores hidden responsive duplicates, accepts identical duplicates, and marks only
a pair with conflicting visible duplicates `AMBIGUOUS`. Target replacement uses a
bounded 100 ms reacquisition schedule. The acquisition watcher includes text changes
so rows rendered before their prices hydrate are acquired without requiring a layout
replacement.

Every browser document has account-free browser-run, tab, frame, and document
identity. A two-second heartbeat reports bridge state plus target, observation, and
outbox state per pair. Bridge connectivity and quote freshness are separate health
dimensions.

The persistent outbox reserves capacity per pair, keeps FIFO order within a pair,
never bypasses a retrying pair head, and services pair groups round-robin. The
collector repeats that structure with bounded per-pair asyncio queues. A failing or
high-rate pair cannot prevent another pair from being attempted.

Raw input is stored before normalized output. Adapter state is keyed by connection,
session, and instrument and invalidated on disconnect. Redis current state uses one
key per pair; TimescaleDB carries instrument and v0.2 base/quote currency fields.
Durable inserts and browser retries are idempotent by stable event ID.

All four feeds are visible display quotes. The rendered rows expose no provider
timestamp or sequence, so v0.2 keeps `provider_event_time=null`,
`sequence=null`, and `PROVIDER_TIMESTAMP_UNAVAILABLE`. Events are labeled
`VISIBLE_DOM`, `DISPLAY_QUOTE`, and `is_provider_tick=false`.

Supervised WebSocket discovery remains OFF by default. It is bounded and redacted
client-side and server-side and is not used by the normal quote path.
