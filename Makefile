.PHONY: setup format lint typecheck test secret-scan infra-up infra-down migrate integration-test smoke load-test run health

setup:
	uv sync --extra dev
	corepack enable
	pnpm install --frozen-lockfile
	pnpm extension:build

format:
	uv run ruff format .

lint:
	uv run ruff check .

typecheck:
	uv run pyright
	pnpm extension:typecheck

test:
	uv run pytest -q packages adapters
	pnpm extension:test

secret-scan:
	gitleaks dir . --no-banner --redact

infra-up:
	docker compose up -d --wait redis timescaledb prometheus grafana

infra-down:
	docker compose down

migrate:
	uv run python scripts/migrate.py

integration-test: infra-up migrate
	uv run pytest -q tests/integration

smoke:
	./scripts/smoke.sh

load-test:
	uv run forex-load-test --rate 1000 --duration 5

run:
	uv run forex-collector

health:
	uv run forex-health
