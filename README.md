# Forex Intelligence Platform — Milestone 1

This repository implements the Milestone 1 replay vertical slice for IC Markets
EUR/USD. Live provider discovery remains explicitly blocked: the public wrapper was
inspected, but no authenticated quote frames were captured or decoded. Nothing here
places or modifies trades.

## Quick start

```bash
cp .env.example .env
make setup
make infra-up
make migrate
make run
```

The collector binds to `127.0.0.1:8001`. In another terminal:

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

Local services:

- Collector health and metrics: <http://127.0.0.1:8001>
- Prometheus: <http://127.0.0.1:9090>
- Grafana: <http://127.0.0.1:3000> (`admin` / `local-dev-change-me`; change it)
- Redis: `127.0.0.1:6380`
- TimescaleDB: `127.0.0.1:55432`

Stop services with `make infra-down`. See [Operations](docs/OPERATIONS.md),
[Security](docs/SECURITY.md), and the [Milestone report](docs/MILESTONE_1_REPORT.md).

