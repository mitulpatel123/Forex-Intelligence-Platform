# Data flow

1. Accept a bounded provider envelope or discovery frame on loopback.
2. Redact sensitive keys and token-shaped text.
3. Hash and persist/publish `RAW_PROVIDER_EVENT`.
4. Validate instrument, timestamp, numeric fields, semantics, ordering, and dedup key.
5. Reconstruct a partial only from fresh state in the same connection/session.
6. Emit `PRICE_TICK` or one or more `DATA_QUALITY_EVENT` records.
7. Update Redis Streams and `latest:quote:IC_MARKETS:EURUSD`.
8. Insert idempotently into TimescaleDB and update metrics beside the data path.

Redis delivery is at-least-once; consumers use groups, processing-attempt fields,
explicit acknowledgements, retry handling, and a dead-letter stream. Database event
keys make repeated writes safe.

HTTP ingestion uses a 10,000-item bounded async queue. Producers receive backpressure;
if insertion cannot complete within 250 ms the request returns 503 and increments
`collector_dropped_events_total`. Shutdown stops readiness, drains accepted work,
then cancels workers and closes storage connections.
