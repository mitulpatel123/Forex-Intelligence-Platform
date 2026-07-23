# Health monitoring

Collector endpoints:

- `GET /health/live`: event loop responsiveness
- `GET /health/ready`: Redis, TimescaleDB, migrations, and adapter initialization
- `GET /health/components`: component, browser bridge, outbox, observer, and
  stale-feed status
- `GET /metrics`: Prometheus exposition

Prometheus scrapes `host.docker.internal:8001` every five seconds. Grafana
auto-provisions “IC Markets EUR/USD — Data Pipeline Health” with connection, age,
rates, latency quantiles, quality, Redis lag, Timescale latency, queue, reconnect,
CPU, memory, and recent quality-counter panels. A stopped collector correctly makes
the Prometheus target down; start `make run` for a healthy scrape.

Bridge connection is based on a fresh authenticated browser heartbeat, not merely a
recent quote. `bridge.connected`, `bridge.observer_ready`,
`bridge.last_browser_message`, `feed.last_valid_tick_age_seconds`, and the adapter
state are reported separately. Prometheus also exports bridge connection, observer,
pending, acknowledged, retry, and dropped counters.
