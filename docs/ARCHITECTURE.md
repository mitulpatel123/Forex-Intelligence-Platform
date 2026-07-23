# Architecture

The implementation is a modular monorepo with one collector process and local
infrastructure.

```text
IC wrapper + MetaTrader iframe
  -> MV3 discovery observer (sanitized EURUSD candidate text only)
  -> authenticated loopback discovery endpoint
  -> immutable RAW_PROVIDER_EVENT

sanitized replay fixture
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

The live mapping is intentionally absent until a real authenticated frame can be
sanitized and decoded. The replay fixture describes the bridge contract, not an
invented provider wire format.

