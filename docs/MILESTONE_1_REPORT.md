# Milestone 1 report

## Result

**MILESTONE 1 REPLAY VERTICAL SLICE PASSED — LIVE PROVIDER DISCOVERY BLOCKED**

Repository: `/Users/mitulpatel/Test Extension/forex-intelligence-platform`

## Environment and installation

The existing Apple Silicon Mac, Homebrew, `uv`, Chrome, and Docker Desktop were
reused. Docker Desktop was started and verified. Homebrew Node 22.23.1 was installed
and linked because the existing Node 25.2.1 was not the active LTS. Gitleaks 8.30.1
was installed for the required local secret scan. Python 3.12.11 was resolved by
`uv`. Exact application and container versions are in `DEPENDENCIES.md`.

## Discovery conclusion

The public entry page was inspected without authentication. It is a CloudFront/S3
served “MetaTrader WebTrader” wrapper that dynamically creates a cross-origin MT4
or MT5 iframe after version/server selection. The wrapper publicly lists six global
MT5 frame hosts. Its captured public HTML hash was
`74451c722239adfc5b7e333732b8165ef5caba53f168fd5e9bbc62522b3f6b39`.

The controlled browser failed during initialization before interactive inspection.
No authenticated EUR/USD message, network subscription, WebSocket schema, DOM
quote, full/partial semantics, timestamp, sequence, or visible-value comparison was
captured. Live status is therefore `BLOCKED_BY_PROVIDER_DISCOVERY`. No endpoint,
symbol ID, selector, or provider schema was fabricated.

## What was built

- Pydantic v0.1 contracts and JSON Schema snapshots for raw, price, quality,
  adapter-status, and feed-health events.
- Decimal-safe EUR/USD normalization and deterministic rules for snapshots,
  partials, stale/reconnect state, numeric validity, skew, duplicates, ordering,
  extreme jump, and extreme spread.
- Immutable raw-first processing with SHA-256 and trace linkage.
- Redis Streams, consumer groups, current quote, retries/dead-letter support, and
  bounded stream trimming.
- TimescaleDB migrations, hypertables, indexes, and idempotent writes.
- Authenticated loopback collector with a 10,000-item bounded queue, 250 ms overflow
  policy, drain-on-shutdown, heartbeat, readiness/liveness/components, and metrics.
- Provisioned Prometheus and Grafana dashboard.
- Replay modes `max`, `realtime`, `step`, and `xN`, plus test reset.
- A narrow MV3 discovery extension injected into only evidenced wrapper/global MT5
  origins. It preserves WebSocket behavior through a constructor proxy, filters
  text EUR/USD candidates, caps payloads at 256 KiB, redacts token patterns, and
  stores raw discovery frames through authenticated localhost.
- The committed fixture is explicitly labeled
  `SIMULATED_BRIDGE_CONTRACT_NOT_PROVIDER_CAPTURE`.

## Commands run and evidence

```text
make format                 PASS
make lint                   PASS
make typecheck              PASS (Pyright 0 errors; TypeScript strict 0 errors)
make test                   PASS (22 Python + 7 extension tests)
make integration-test       PASS (1 real Redis/TimescaleDB integration test)
make secret-scan            PASS (357.77 KB scanned; no leaks)
make smoke                  PASS
make load-test              PASS
```

Smoke replay result:

```json
{"duplicates":0,"elapsed_seconds":0.035432,"invalid_events":1,"out_of_order_events":0,"total_raw_events":4,"valid_ticks":3}
```

The smoke test also verified collector readiness/liveness, metrics, Redis current
state and streams, raw/tick SQL rows, Prometheus target `UP`, Grafana health, and the
auto-provisioned dashboard UID `icm-eurusd-health`.

Load result (in-process validation path, not an HFT claim):

```json
{"actual_elapsed_seconds":5.0001,"dropped_count":0,"duration_seconds":5,"input_rate":1000,"max_queue_depth":0,"p50_latency_ms":0.1787,"p95_latency_ms":0.4248,"p99_latency_ms":1.1289,"peak_memory_bytes":59113472,"processed_count":5000}
```

Actual replay-produced sample:

```json
{
  "event_type": "PRICE_TICK",
  "schema_version": "0.1",
  "provider": "IC_MARKETS",
  "instrument": "EURUSD",
  "bid": "1.08543",
  "ask": "1.08546",
  "mid": "1.085445",
  "spread": "0.00003",
  "spread_pips": "0.3",
  "pip_size": "0.0001",
  "is_snapshot": false,
  "changed_fields": ["ask"],
  "sequence": 3,
  "quality_status": "GOOD"
}
```

This is replay evidence from the simulated bridge-contract fixture, not live market
data.

## Security review

Loopback binding, exact extension origins, no `<all_urls>`, local code only, no
trade interactions, size/origin/schema validation, recursive redaction, 0600 random
bridge token, ignored captures/secrets, and Gitleaks were verified. The local
Grafana development password must be changed for any non-local use. No provider
credential, cookie, token, account number, balance, or personal data was collected.

## Limitations and blocker

- Real quote delivery and provider schema remain unknown.
- Binary/compressed frames and symbol aliases may bypass the current text candidate
  filter; discovery must determine the narrowest safe observer change.
- The bridge service worker uses a generic browser session label until real
  connection/session semantics are discovered.
- The replay fixture proves platform behavior, not exact provider-to-contract
  normalization.
- UUID4 is used because the standard library/runtime selection does not expose UUIDv7.
- Prometheus reports the collector down whenever the host collector is stopped; this
  is correct behavior.

## Recommended Milestone 2

Keep scope restricted to finishing provider discovery: have the user manually load
the extension, log in/MFA, select one MT5 server and EUR/USD, capture a short ignored
sample, sanitize it, compare decoded bid/ask with the visible quote, document socket,
heartbeat, reconnect, subscription, timestamp/sequence, and snapshot/partial
semantics, then replace only the provisional bridge mapping with an exact
fixture-backed live adapter. Do not add strategies, trading, news, indicators, or
additional instruments until that live slice passes.
