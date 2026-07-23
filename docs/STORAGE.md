# Storage

`001_initial.sql` creates TimescaleDB hypertables for raw events, price ticks,
quality events, and adapter heartbeats. `002_display_quote_provenance.sql` adds
durable source qualification. Additive migration
`003_price_tick_v02_currencies.sql` adds nullable `base_currency` and
`quote_currency` plus an instrument/normalized-time index. Historical v0.1 rows
are not rewritten by Milestone 2.

New v0.2 rows carry the registry-derived base/quote currency and pair pip size.
The four current Redis keys are:

```text
latest:quote:IC_MARKETS:EURUSD
latest:quote:IC_MARKETS:GBPUSD
latest:quote:IC_MARKETS:USDJPY
latest:quote:IC_MARKETS:AUDUSD
```

Per-pair health uses `health:feed:IC_MARKETS:<instrument>`. Global Redis Streams
retain `instrument` inside each serialized event.

Use [scripts/verify_milestone_2.sql](../scripts/verify_milestone_2.sql) for latest
rows, counts, warnings, reconciliation, and stale checks. No retention or
compression policy is enabled. Raw discovery content is local, redacted, ignored
by Git, and should be governed by local retention policy.
