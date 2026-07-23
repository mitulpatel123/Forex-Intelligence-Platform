# Troubleshooting

- Docker unavailable: open Docker Desktop and wait for `docker info`.
- Collector not ready: inspect `docker compose ps`, then run `make migrate`.
- Extension `error`: start the collector and verify the 0600 local token is saved
  in extension Options.
- `disconnected`: distinguish a missing bridge heartbeat from pair freshness at
  `/health/components`.
- Pair `MISSING`: make that exact Market Watch row visible and confirm the table has
  exact Symbol, Bid, and Ask headers.
- Pair `AMBIGUOUS`: remove conflicting visible responsive/duplicate layouts.
  Identical duplicates and hidden layouts are accepted/ignored automatically.
- Pair `STALE`: confirm its displayed values are updating; the other pairs should
  remain healthy.
- Pending outbox: verify readiness/token and inspect that pair's retry/drop/reject
  counters. Pending events survive service-worker and collector restart.
- USDJPY rejected: display precision must be 2–4 decimals and its pip is `0.01`.
- Generated drift: run `make generate-contracts`, then `make check-generated`.
- Prometheus target down: start `make run`; the collector is a host process.
- Discovery: leave it OFF during normal operation; never invent or bypass a
  provider decoder.
- Test reset: use replay `--publish --reset` only against the local test stack.
