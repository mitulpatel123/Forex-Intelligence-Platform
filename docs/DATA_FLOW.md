# Data flow

1. Generate Python and TypeScript pair definitions from the canonical registry.
2. Locate each visible supported Market Watch row by exact Symbol/Bid/Ask headers.
3. Validate pair-specific decimal precision and broad price bounds.
4. Emit only a changed pair; unchanged pairs are not re-emitted.
5. Assign a stable UUID and persist the event in its pair's bounded outbox group.
6. Service groups round-robin while preserving FIFO within each pair.
7. POST the full display snapshot to the token-authenticated loopback endpoint.
8. Accept into the pair's bounded collector queue or return retryable 503.
9. Store/publish `RAW_PROVIDER_EVENT` before normalization.
10. Validate against the registry and pair-specific state, dedup, pip, jump, spread,
    ordering, and timestamp policy.
11. Emit `PRICE_TICK` v0.2 and relevant quality events.
12. Write TimescaleDB, global Redis Streams, the pair's latest key, feed-health key,
    and per-pair metrics.
13. Acknowledge the browser event; only then remove it from the persistent outbox.

Browser reconciliation is evaluated per pair:

```text
produced = acknowledged + pending + dropped
rejected is a classified subset of dropped
```

The collector acknowledges a repeated event ID as a duplicate without adding a
second durable raw or normalized row. Extension service-worker and collector
restarts therefore preserve at-least-once delivery without duplicate history.
