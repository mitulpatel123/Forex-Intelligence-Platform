# Architecture

The implementation is a modular monorepo with one collector process and local
infrastructure.

```text
IC wrapper + MetaTrader iframe
  -> MT5 binary WebSocket transport
  -> visible EURUSD market-watch row
  -> MV3 narrow DOM quote observer
  -> authenticated loopback provider endpoint
  -> immutable RAW_PROVIDER_EVENT
  -> IC Markets adapter
  -> deterministic validation/state reconstruction
  -> PRICE_TICK + DATA_QUALITY_EVENT
  -> Redis Streams/current quote + TimescaleDB
  -> Prometheus metrics -> provisioned Grafana dashboard
```

The adapter SDK separates the `LIVE_FX_QUOTE` capability from IC Markets-specific
translation. Raw input is stored before normalized output. State is keyed by
connection, session, and instrument, and is invalidated on disconnect. Consumers
use Redis consumer groups and acknowledge only after work succeeds. Durable inserts
are idempotent through composite primary keys.

The observed MT5 transport is a binary `ArrayBuffer` WebSocket using a provider
codec. The project does not reverse engineer or bypass that codec. The evidence-backed
fallback observes only the browser-rendered EURUSD symbol, bid, and ask. Since that
surface exposes no provider timestamp or sequence, normalized ticks retain a null
provider timestamp and an explicit `PROVIDER_TIMESTAMP_UNAVAILABLE` warning.
