# Operations

Setup/start:

```bash
cp .env.example .env
make setup
make infra-up
make migrate
make run
```

Replay:

```bash
uv run forex-replay adapters/ic_markets/fixtures/replay_bridge.jsonl --speed max --publish
```

Supported speeds are `max`, `realtime`, `step`, and `xN`. Add `--reset` only with
`--publish` to clear test tables/streams. Stop with Ctrl-C, then `make infra-down`.

Extension build/load:

```bash
pnpm extension:build
```

Open `chrome://extensions`, enable Developer mode, load
`apps/browser_bridge` unpacked, start the collector, open extension Options, and
copy the local token from `.local/bridge-token`. This token is only for localhost;
never enter an IC Markets credential. Manually log in/MFA and display EURUSD in
Market Watch. The popup should change from `waiting for EUR/USD` to `receiving`.
Do not use trading controls.

Verify the live path:

```bash
curl -fsS http://127.0.0.1:8001/health/components
docker compose exec -T redis redis-cli XLEN normalized.price_tick
docker compose exec -T timescaledb psql -U forex -d forex -c \
  "SELECT received_time,bid,ask,quality_status FROM price_ticks ORDER BY received_time DESC LIMIT 5"
```

`provider_event_time` is null and quality is `WARNING` for this collection method
because the visible terminal row does not expose the provider timestamp or sequence.
