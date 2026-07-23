# Dependencies

Resolved application packages are locked by `uv.lock` and `pnpm-lock.yaml`.
Direct pins are in `pyproject.toml` and `package.json`.

Key runtime versions:

- Python 3.12.11; uv 0.8.17
- Pydantic 2.11.7; FastAPI 0.116.1; Uvicorn 0.35.0
- redis-py 6.2.0; Psycopg 3.2.9; psycopg-pool 3.3.1
- prometheus-client 0.22.1; structlog 25.4.0
- Pytest 8.4.1; Ruff 0.12.7; Pyright 1.1.403
- Node 22.23.1; pnpm 10.15.1; TypeScript 5.8.3; Vitest 3.2.4
- `redis:7.4.2-alpine`
- `timescale/timescaledb:2.18.1-pg16`
- `prom/prometheus:v3.2.1`
- `grafana/grafana:11.5.2`

Container tags are exact, not floating. The lockfiles contain transitive versions.

