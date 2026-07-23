# Architecture decisions

- [ADR-001](adr/ADR-001-ic-markets-collection-method.md) selects the narrow visible
  display-quote fallback for the opaque binary MT5 transport.
- [ADR-002](adr/ADR-002-multi-instrument-contract-and-fairness.md) freezes v0.1,
  introduces registry-backed v0.2, and applies per-pair fairness at both bounded
  queues.
- Decimal strings cross JSON boundaries and PostgreSQL uses `NUMERIC`.
- Raw records precede normalization and carry stable event IDs, hashes, and traces.
- Redis is current/streaming state; TimescaleDB is durable history.
- Unknown semantics fail closed. Missing provider time remains null and becomes a
  quality warning, never an invented timestamp.
