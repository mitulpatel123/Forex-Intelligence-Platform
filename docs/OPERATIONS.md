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
pnpm exec tsc -p apps/browser_bridge/tsconfig.json
```

Open `chrome://extensions`, enable Developer mode, load
`apps/browser_bridge` unpacked, start the collector, open extension Options, and
copy the local token from `.local/bridge-token`. This token is only for localhost;
never enter an IC Markets credential. Manually log in/MFA, select MT5/server and
EUR/USD, then inspect ignored discovery records. Do not use trading controls.

