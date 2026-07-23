# Testing

```bash
make generate-contracts
make check-generated
make format
make lint
make typecheck
make test
make integration-test
make smoke
make load-test
make secret-scan
```

Python tests cover the canonical registry, deterministic generation, v0.1
compatibility, v0.2 serialization, all pair currencies and Decimal math, the
USDJPY `0.01` pip invariant, pair warnings, independent state/dedup, session
invalidation, fair scheduling, per-pair capacity, and graceful drain.
Timestamp coverage includes normal/equal time, negative skew, delayed outbox,
collector restart ordering, page-session reset, independent four-pair sequences,
malicious provider/collector claims, and local wall-clock adjustment.

Extension tests cover four-row discovery, reordered rows/columns, exact headers,
extra numeric columns, hidden and responsive duplicates, identical/conflicting
duplicates, missing/malformed isolation, USDJPY precision, row/table replacement,
symbol remove/re-add, unchanged suppression, bounded discovery, persistent retry,
restart recovery, round-robin/FIFO behavior, reserved capacity, rejection, and
duplicate drain calls.
DOM coverage includes same-price row reacquisition. Integration coverage also
proves one active tab per pair, standby suppression, deterministic failover, and
safe behavior when the old active tab returns.

Real Redis/TimescaleDB integration sends every pair, resends stable event IDs,
proves one durable row per unique observation, checks four latest keys and global
stream instruments, validates per-pair health isolation and redaction, and runs
legacy and mixed replay fixtures.

Smoke starts infrastructure and collector, migrates, replays mixed data, and checks
four Redis keys, SQL, metrics, Prometheus, and the provisioned Grafana dashboard.
Mixed load uses a deterministic 40/25/20/15 distribution and reports processed,
dropped, latency percentiles, maximum queue depth, memory, and starvation.

Live soak, restart recovery, and pair-removal isolation are recorded separately in
the Milestone report; replay results are never presented as live evidence.
