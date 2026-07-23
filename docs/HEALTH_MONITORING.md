# Health monitoring

Collector endpoints:

- `GET /health/live`: event loop responsiveness
- `GET /health/ready`: Redis, TimescaleDB, migrations, and adapter initialization
- `GET /health/components`: component and stale-feed status
- `GET /metrics`: Prometheus exposition

Prometheus scrapes `host.docker.internal:8001` every five seconds. Grafana
auto-provisions “IC Markets EUR/USD — Data Pipeline Health” with connection, age,
rates, latency quantiles, quality, Redis lag, Timescale latency, queue, reconnect,
CPU, memory, and recent quality-counter panels. A stopped collector correctly makes
the Prometheus target down; start `make run` for a healthy scrape.

