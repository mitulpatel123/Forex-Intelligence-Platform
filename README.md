# Forex Intelligence Platform — Milestone 2

This local-first pipeline captures four visible IC Markets Market Watch display
quotes: `EURUSD`, `GBPUSD`, `USDJPY`, and `AUDUSD`. A Manifest V3 browser bridge
observes only exact Symbol/Bid/Ask cells, persists observations in a bounded fair
outbox, and removes them only after collector acknowledgement. The collector
validates, normalizes, stores, streams, and monitors each pair independently.

These are `DISPLAY_QUOTE` observations, not provider-native ticks. The project does
not place or modify trades, inspect account controls, or request provider
credentials.

## Quick start

```bash
cp .env.example .env
make setup
make infra-up
make migrate
make run
```

The collector binds to `127.0.0.1:8001`. Build and load the extension as documented
in [Operations](docs/OPERATIONS.md), or run the deterministic four-pair replay:

```bash
uv run forex-replay \
  adapters/ic_markets/fixtures/replay_four_pair_mixed.jsonl \
  --speed max --publish
```

Run every local gate:

```bash
make generate-contracts
make check-generated
make format
make lint
make typecheck
make test
make integration-test
make smoke
make load-test
make secret-scan
```

Local services:

- Collector health and metrics: <http://127.0.0.1:8001>
- Prometheus: <http://127.0.0.1:9090>
- Grafana: <http://127.0.0.1:3000> (`admin` / `local-dev-change-me`; change it)
- Redis: `127.0.0.1:6380`
- TimescaleDB: `127.0.0.1:55432`

Stop services with `make infra-down`. See the [Milestone 2 report](docs/MILESTONE_2_REPORT.md),
[instrument registry](docs/INSTRUMENT_REGISTRY.md), [operations](docs/OPERATIONS.md),
and [security](docs/SECURITY.md).
