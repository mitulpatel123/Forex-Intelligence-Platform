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
- No frames: the provider may use binary/compressed frames or an unlisted origin;
  record the observation and do not invent a decoder.
- Stale partials: obtain a fresh snapshot in the same session; reconnect clears state.
- Database data reset: use replay `--publish --reset` only for the local test stack.

