# ADR-002: Multi-instrument contract and fairness

- Status: Accepted
- Date: 2026-07-23
- Baseline: `6372a7ab236b494eb181cb1d5cec13430f93d3da`

## Context

Milestone 1 froze `PRICE_TICK` v0.1 for EURUSD and proved an acknowledged visible
display-quote path. Milestone 2 adds GBPUSD, USDJPY, and AUDUSD. Silently changing
v0.1 would invalidate historical meaning, while a single global FIFO could allow a
high-rate or failing pair to starve the others.

## Decision

1. Keep `PriceTickV01` frozen and parse it through a discriminated compatibility
   union.
2. Emit new live observations as registry-backed `PRICE_TICK` v0.2 with explicit
   base and quote currencies.
3. Use one canonical JSON registry and deterministic Python/TypeScript generation.
4. Add nullable TimescaleDB currency columns without rewriting historical rows.
5. Maintain adapter state by `(connection_id, session_id, instrument)`.
6. Partition browser outbox capacity among four pair groups plus discovery,
   preserve FIFO within a group, and select groups round-robin.
7. Use bounded per-pair collector queues with the same round-robin/FIFO properties.
8. Keep global Redis streams but use per-pair latest and health keys.

## Consequences

- USDJPY math cannot inherit a `0.0001` pip assumption.
- A backed-up or repeatedly failing pair does not prevent attempts for other pairs.
- There is no cross-pair global-order guarantee; none is required.
- Reserved per-group outbox capacity may reject a pair before unused capacity in a
  different group is consumed. The explicit drop is preferable to starvation.
- Existing v0.1 records remain valid, while v0.2 consumers must handle the new
  currency fields.
- All four feeds remain display quotes rather than provider-native ticks.
