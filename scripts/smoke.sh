#!/bin/sh
set -eu

docker compose up -d --wait redis timescaledb prometheus grafana
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

uv run forex-replay adapters/ic_markets/fixtures/replay_bridge.jsonl --publish --reset
curl -fsS http://127.0.0.1:8001/health/live | grep -q '"status":"UP"'
curl -fsS http://127.0.0.1:8001/metrics | grep -q 'normalized_ticks_total'
docker compose exec -T redis redis-cli GET latest:quote:IC_MARKETS:EURUSD | grep -q PRICE_TICK
docker compose exec -T timescaledb psql -U forex -d forex -Atc \
  "SELECT count(*) FROM price_ticks" | grep -Eq '^[1-9][0-9]*$'
docker compose exec -T timescaledb psql -U forex -d forex -Atc \
  "SELECT count(*) FROM raw_provider_events" | grep -Eq '^[1-9][0-9]*$'
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
  'http://127.0.0.1:3000/api/search?query=IC%20Markets' | grep -q 'icm-eurusd-health'
echo "SMOKE PASSED"
