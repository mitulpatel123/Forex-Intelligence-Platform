#!/bin/sh
set -eu

if [ "${FIP_SMOKE_REUSE_DATA_SERVICES:-false}" = "true" ]; then
  docker compose up --no-deps -d --wait prometheus grafana
else
  docker compose up -d --wait redis timescaledb prometheus grafana
fi
uv run python scripts/migrate.py

uv run forex-collector >.smoke-collector.log 2>&1 &
collector_pid=$!
trap 'kill "$collector_pid" 2>/dev/null || true' EXIT

attempt=0
until curl -fsS http://127.0.0.1:8001/health/ready >/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 30 ]; then
    cat .smoke-collector.log
    exit 1
  fi
  sleep 1
done

uv run forex-replay adapters/ic_markets/fixtures/replay_four_pair_mixed.jsonl --publish --reset
curl -fsS http://127.0.0.1:8001/health/live | grep -q '"status":"UP"'
curl -fsS http://127.0.0.1:8001/metrics | grep -q 'normalized_ticks_total'
uv run python scripts/smoke_verify.py
curl -fsS http://127.0.0.1:9090/-/healthy >/dev/null
attempt=0
until curl -fsS http://127.0.0.1:9090/api/v1/targets | grep -q '"health":"up"'; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 20 ]; then
    echo "Prometheus did not report an UP collector target"
    exit 1
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:3000/api/health | grep -Eq '"database"[[:space:]]*:[[:space:]]*"ok"'
grafana_user=${GF_SECURITY_ADMIN_USER:-admin}
grafana_password=${GF_SECURITY_ADMIN_PASSWORD:-local-dev-change-me}
curl -fsS -u "$grafana_user:$grafana_password" \
  'http://127.0.0.1:3000/api/search?query=IC%20Markets' | grep -q 'icm-four-pair-health'
echo "SMOKE PASSED"
