# Architecture decisions

- ADR-001 selects structured browser-received messages as the preferred discovery
  target, with capture-only instrumentation until the format is known.
- A single async collector replaces unnecessary microservices.
- Decimal strings cross JSON boundaries and PostgreSQL uses `NUMERIC`.
- Redis is live/streaming state; TimescaleDB is durable history.
- Raw records precede normalization and carry SHA-256 hashes and trace IDs.
- Unknown message semantics fail closed; no value or timestamp is guessed.
- Test containers use ports 6380 and 55432 because local 6379 and 5432/5433 were occupied.

