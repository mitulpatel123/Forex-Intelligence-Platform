# Forex Intelligence Platform — Milestone 1

This repository implements the Milestone 1 live vertical slice for IC Markets
EUR/USD. An authenticated browser bridge observes only the displayed EURUSD bid/ask,
persists each observation in a bounded retry outbox, and removes it only after the
collector acknowledges it. The collector validates, normalizes, stores, streams,
and monitors the display quote. This is explicitly not a claim of provider-native
tick completeness. Nothing here places or modifies trades.

## Quick start

```bash
cp .env.example .env
make setup
make infra-up
make migrate
make run
```

The collector binds to `127.0.0.1:8001`. Build and load the extension as documented
in [Operations](docs/OPERATIONS.md), or exercise the deterministic replay path:

```bash
uv run forex-replay adapters/ic_markets/fixtures/replay_bridge.jsonl --publish
```

Run all gates:

```bash
make format
make lint
make typecheck
make test
make integration-test
make smoke
make load-test
```

GitHub Actions runs format, lint, type, unit, extension/manifest safety, integration,
and secret-scan gates on every pull request.

Local services:

- Collector health and metrics: <http://127.0.0.1:8001>
- Prometheus: <http://127.0.0.1:9090>
- Grafana: <http://127.0.0.1:3000> (`admin` / `local-dev-change-me`; change it)
- Redis: `127.0.0.1:6380`
- TimescaleDB: `127.0.0.1:55432`

Stop services with `make infra-down`. See [Operations](docs/OPERATIONS.md),
[Security](docs/SECURITY.md), and the [Milestone report](docs/MILESTONE_1_REPORT.md).
