# Operations

## Start and replay

```bash
cp .env.example .env
make setup
make infra-up
make migrate
make run
```

```bash
uv run forex-replay \
  adapters/ic_markets/fixtures/replay_four_pair_mixed.jsonl \
  --speed max --publish
```

Replay speeds are `max`, `realtime`, `step`, and `xN`. Use `--reset` only with
`--publish` against the local test stack.

## Build and load the extension

```bash
pnpm extension:build
```

Open `chrome://extensions`, enable Developer mode, and load
`apps/browser_bridge` unpacked. Open extension Options and copy the local token from
`.local/bridge-token`. This is a localhost token, not an IC Markets credential.

The user manually logs in and completes MFA. Add `EURUSD`, `GBPUSD`, `USDJPY`, and
`AUDUSD` to Market Watch and resize it so every row is rendered. Reload the
unpacked extension. Do not use trade or account controls.

The popup shows overall bridge status and status/pending/retry/drop/reject values
per pair. All four should reach `READY`, pending should settle to zero, and drops
and rejections should stay zero. Discovery mode must remain OFF for normal use.

## Verify

```bash
curl -fsS http://127.0.0.1:8001/health/components
curl -fsS http://127.0.0.1:8001/metrics
for pair in EURUSD GBPUSD USDJPY AUDUSD; do
  docker compose exec -T redis redis-cli GET \
    "latest:quote:IC_MARKETS:$pair"
done
docker compose exec -T timescaledb psql -U forex -d forex \
  -f /dev/stdin < scripts/verify_milestone_2.sql
```

Each live row should be `schema_version=0.2`, `source=VISIBLE_DOM`,
`observation_level=DISPLAY_QUOTE`, `is_provider_tick=false`, with null provider
time and `PROVIDER_TIMESTAMP_UNAVAILABLE`.

## Restart recovery

While collection is active, stop only the collector with Ctrl-C. The extension's
per-pair pending counts should rise. Restart `make run`; the same stable event IDs
must retry, pending must return to zero, and SQL must retain one raw/normalized row
per event ID.

## Pair isolation

Temporarily remove or hide one Market Watch pair. Only that pair should become
`MISSING` or `STALE`; the other three must continue. Restore it and confirm
automatic reacquisition. Conflicting duplicate ambiguity is validated with test
fixtures, not by unsafe page manipulation.

Stop the collector with Ctrl-C and infrastructure with `make infra-down`.
