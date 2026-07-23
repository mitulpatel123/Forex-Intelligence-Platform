# Testing

Commands are the source of truth:

```bash
make lint
make typecheck
make test
make integration-test
make smoke
make load-test
```

Unit tests cover Decimal math, snapshots, both partial sides, unsafe/stale state,
reconnect invalidation, price/timestamp validation, crossed quotes, clock skew,
duplicates, sequence and time ordering, plausibility warnings, redaction, hashes,
and derived contract validation. Extension tests cover MV3/allowlists, origin and
shape validation, payload limits, and token redaction.

Integration uses real local Redis and TimescaleDB. Smoke orchestrates all four
containers, runs migrations and collector, replays the fixture, verifies Redis,
SQL rows, health/metrics, Prometheus, and Grafana, and exits nonzero on failure.

