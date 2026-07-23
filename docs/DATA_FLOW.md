# Data flow

1. Observe a changed, visible EURUSD bid/ask pair in the authenticated terminal.
2. Accept its bounded provider envelope on authenticated loopback.
3. Redact sensitive keys and token-shaped text.
4. Hash and persist/publish `RAW_PROVIDER_EVENT`.
5. Validate instrument, timestamp availability, numeric fields, semantics, ordering,
   and the dedup key.
6. Reconstruct a partial only from fresh state in the same connection/session.
7. Emit `PRICE_TICK` plus the timestamp-availability quality warning.
8. Update Redis Streams and `latest:quote:IC_MARKETS:EURUSD`.
9. Insert idempotently into TimescaleDB and update metrics beside the data path.

Redis delivery is at-least-once; consumers use groups, processing-attempt fields,
explicit acknowledgements, retry handling, and a dead-letter stream. Database event
keys make repeated writes safe.

HTTP ingestion uses a 10,000-item bounded async queue. Producers receive backpressure;
if insertion cannot complete within 250 ms the request returns 503 and increments
`collector_dropped_events_total`. Shutdown stops readiness, drains accepted work,
then cancels workers and closes storage connections.
