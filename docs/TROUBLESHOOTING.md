# Troubleshooting

- Docker socket missing: open Docker Desktop and wait for `docker info`.
- Port collision: keep project defaults 6380/55432/8001/9090/3000 or adjust both
  Compose and `.env`.
- Collector not ready: inspect Redis/Timescale health with `docker compose ps`, then
  run `make migrate`.
- Prometheus target down: start `make run`; the collector is intentionally not a
  container.
- Extension says error: start the collector, confirm the 0600 token exists, and
  save it in extension Options.
- Pending outbox does not drain: keep the terminal open, verify collector readiness
  and token, and inspect retry/dropped counters. Pending events survive worker
  suspension and extension service-worker restarts.
- Waiting for EUR/USD: confirm the visible Market Watch table has exact Symbol, Bid,
  and Ask headers and one unambiguous EURUSD row.
- Binary discovery: keep it OFF during normal operation; never invent or bypass a
  provider decoder.
- Stale partials: obtain a fresh snapshot in the same session; reconnect clears state.
- Database data reset: use replay `--publish --reset` only for the local test stack.
