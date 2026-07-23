# Health monitoring

Collector endpoints:

- `GET /health/live`: event-loop responsiveness
- `GET /health/ready`: Redis, TimescaleDB, and migrations
- `GET /health/components`: bridge plus per-pair target, freshness, rate, queue,
  quality, outbox state, active tab/frame/document identity, and multiple-source state
- `GET /metrics`: Prometheus exposition

Overall adapter state is:

- `DISCONNECTED` when no authenticated bridge heartbeat is fresh;
- `INITIALIZING` while connected but no supported quote is ready;
- `CONNECTED` only when all four pairs are healthy;
- `DEGRADED` when one or more pairs is missing, ambiguous, stale, or unhealthy.

One stale pair does not mark the other three stale. `MISSING`, `AMBIGUOUS`, and
`STALE` retain different meanings. See [Multi-pair health](MULTI_PAIR_HEALTH.md).

Prometheus exports pair-labeled raw, normalized, invalid, duplicate, out-of-order,
stale, queue, drop, latency, latest bid/ask/spread, and browser outbox metrics.
It also exports per-pair browser-to-collector delay histograms, active-source
conflict state, standby suppressions, and the bounded dedup cache size. Grafana
shows p50, p95, and p99 browser-to-collector delay by pair.
Grafana provisions “IC Markets Four-Pair — Data Pipeline Health” with UID
`icm-four-pair-health`.
