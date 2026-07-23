# Architecture

The implementation is a modular monorepo with one collector process and local
infrastructure.

```text
IC wrapper + MetaTrader iframe
  -> MT5 binary WebSocket transport
  -> visible EURUSD market-watch row
  -> MV3 targeted DOM quote observer
  -> persistent bounded outbox + retry/ack
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

Every browser document receives an account-free random session identifier combined
with browser-run, tab, and frame identity. A two-second browser heartbeat reports
observer readiness and outbox counters independently from feed freshness. The
collector health response separates bridge connection, last browser message, last
valid display quote, and stale-feed state.

The observed MT5 transport is a binary `ArrayBuffer` WebSocket using a provider
codec. The project does not reverse engineer or bypass that codec. The evidence-backed
fallback observes only the browser-rendered EURUSD symbol, bid, and ask. Since that
surface exposes no provider timestamp or sequence, normalized ticks retain a null
provider timestamp and an explicit `PROVIDER_TIMESTAMP_UNAVAILABLE` warning. Events
are labeled `VISIBLE_DOM`, `DISPLAY_QUOTE`, and `is_provider_tick=false`.

WebSocket discovery is disabled by default. When explicitly enabled for supervised
troubleshooting, candidates are size-limited, redacted in the extension, redacted
again by the collector, and never retained in extension-local last-frame storage.
