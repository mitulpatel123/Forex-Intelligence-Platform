# Storage

`001_initial.sql` creates TimescaleDB hypertables for raw events, price ticks,
quality events, and adapter heartbeats. `002_display_quote_provenance.sql` adds
durable source qualification. Additive migration
`003_price_tick_v02_currencies.sql` adds nullable `base_currency` and
`quote_currency` plus an instrument/normalized-time index. Historical v0.1 rows
are not reclassified by Milestone 2. `004_local_pipeline_timestamps.sql` adds
browser observation, collector receipt, database creation, document session,
observation sequence, and local delay columns.

For visible display observations:

```text
provider_event_time = null
received_time = browser_observed_at        # compatibility meaning
collector_received_at = collector server clock at endpoint entry
normalized_time = validator clock after validation
database_created_at = database clock during INSERT
```

Strict local ordering is queried by
`document_session_id, instrument, observation_sequence`. Browser time is not
provider time and is not the ordering authority within a document session.

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
