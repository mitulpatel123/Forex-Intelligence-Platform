# Architecture decisions

- ADR-001 records the observed binary MT5 transport and selects the narrow visible
  EURUSD row as the compliant collection fallback.
- A single async collector replaces unnecessary microservices.
- Decimal strings cross JSON boundaries and PostgreSQL uses `NUMERIC`.
- Redis is live/streaming state; TimescaleDB is durable history.
- Raw records precede normalization and carry SHA-256 hashes and trace IDs.
- Unknown message semantics fail closed; the unavailable provider timestamp remains
  null and is reported as a warning rather than guessed.
- Test containers use ports 6380 and 55432 because local 6379 and 5432/5433 were occupied.
