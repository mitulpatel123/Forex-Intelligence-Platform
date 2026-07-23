# Data flow

1. Observe a changed, visible EURUSD bid/ask pair in the authenticated terminal.
2. Assign an observation UUID and persist it in the extension's 1,000-item outbox.
3. POST with a five-second timeout and retry the same UUID after temporary failures.
4. Remove the observation only after authenticated collector acknowledgement.
5. Redact sensitive keys and token-shaped text server-side.
6. Hash and persist/publish the idempotent `RAW_PROVIDER_EVENT`.
7. Validate instrument, timestamp availability, numeric fields, semantics, ordering,
   and the dedup key.
8. Reconstruct a partial only from fresh state in the same connection/session.
9. Emit `PRICE_TICK` plus the timestamp-availability quality warning.
10. Update Redis Streams and `latest:quote:IC_MARKETS:EURUSD`.
11. Insert idempotently into TimescaleDB and update metrics beside the data path.

Redis delivery is at-least-once; consumers use groups, processing-attempt fields,
explicit acknowledgements, retry handling, and a dead-letter stream. Database event
keys make repeated writes safe.

The browser outbox satisfies:

```text
produced = acknowledged + pending + dropped + rejected
```

Acknowledged observation UUIDs are idempotent at the collector, including an
acknowledgement lost after the database commit.

HTTP ingestion uses a 10,000-item bounded async queue. Producers receive backpressure;
if insertion cannot complete within 250 ms the request returns 503 and increments
`collector_dropped_events_total`. Shutdown stops readiness, drains accepted work,
then cancels workers and closes storage connections.
