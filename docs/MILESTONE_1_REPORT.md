# Milestone 1 report

## Result

**MILESTONE 1 LIVE DISPLAY-QUOTE PROTOTYPE PASSED — PR HARDENING IMPLEMENTED**

Repository: `/Users/mitulpatel/Test Extension/forex-intelligence-platform`

## Live provider evidence

On 2026-07-23 an authenticated IC Markets MT5-3 terminal displayed live EURUSD
quotes and the extension reported `receiving`. Discovery established this path:

```text
IC Markets wrapper
  -> cross-origin MetaTrader 5 terminal
  -> wss://<terminal-host>/terminal (binary ArrayBuffer provider codec)
  -> visible EURUSD Market Watch bid/ask
  -> narrow MV3 observer
  -> authenticated 127.0.0.1 collector
```

The project does not reverse engineer the binary codec or capture broad binary
traffic. It reads only the visible EURUSD symbol, bid, and ask, never interacts
with order controls, and never reads account/session fields.

This is a rendered `DISPLAY_QUOTE`, not a provider-native tick. It does not prove
that every wire update was displayed, preserve provider precision, or support an
HFT-quality completeness claim.

The rendered row exposes no provider timestamp or sequence. Live observations are
full snapshots with `provider_event_time=null`, `sequence=null`, and explicit
`PROVIDER_TIMESTAMP_UNAVAILABLE` warning status. No timestamp is invented.

## Validated live vertical slice

During the validation window:

- the extension popup reported `receiving`;
- collector liveness was `UP` and readiness was `READY`;
- Redis and TimescaleDB were `UP`, migrations were `CURRENT`;
- live raw events and normalized ticks increased continuously;
- Redis `latest:quote:IC_MARKETS:EURUSD` contained the current v0.1 `PRICE_TICK`;
- TimescaleDB stored raw observations, normalized ticks, and quality warnings;
- the feed reported `HEALTHY`;
- Prometheus reported the collector target `up`;
- Grafana reported database status `ok`;
- invalid, duplicate, out-of-order, and stale counters were all zero.

One validated live sample was bid `1.13743`, ask `1.13744`, mid `1.137435`,
spread `0.00001`, and spread `0.1` pips. The browser-visible quote continued to
change after this sample. A reviewed market-data-only fixture is committed at
`adapters/ic_markets/fixtures/live_visible_dom.jsonl`.

## PR-hardening live soak

A 15-minute authenticated soak ran from `2026-07-23T18:48:10Z` through
`2026-07-23T19:03:11Z` against the hardened extension and local collector:

| Measure | Result |
| --- | ---: |
| DOM observations produced | 669 |
| Collector acknowledgements | 669 |
| Accepted unique backend raw events | 669 |
| Normalized rows | 669 |
| Outbox retries | 0 |
| Browser-side drops / rejections | 0 / 0 |
| Backend drops | 0 |
| Zero-spread display occurrences | 239 |
| Maximum observed processing delay | 144.640 ms |
| Extension reconnects | 0 |

The required delivery invariant held exactly: 669 acknowledged browser events
equaled 669 unique accepted raw events, with no rejected observations. All 669
normalized rows had `VISIBLE_DOM` / `DISPLAY_QUOTE` / `is_provider_tick=false`
provenance. Pending returned to zero throughout sampled heartbeats.

Equal displayed bid and ask values were manually verified in two distinct cells of
the exact EURUSD Market Watch row; they were not the same value selected twice.
The bridge stayed connected and observer-ready. Feed freshness was healthy while
the displayed quote changed and correctly became stale during a final 6.7-second
no-change interval without misreporting the browser bridge as disconnected.

After the measured window, a controlled collector restart exercised recovery on
the final patched backend: three delivery retries were retained and acknowledged,
pending returned to zero, and no event was dropped or rejected.

## What was built

- Pydantic v0.1 contracts and JSON Schema snapshots for raw, price, quality,
  adapter-status, and feed-health events.
- Decimal-safe EURUSD normalization and deterministic rules for snapshots,
  partials, invalid values, duplicates, stale state, ordering, jumps, and spreads.
- Immutable raw-first storage with SHA-256 and trace linkage.
- Redis Streams, current quote, consumer groups, retry/dead-letter support, and
  bounded trimming.
- TimescaleDB hypertables, indexes, and idempotent writes.
- Authenticated loopback collector with a bounded queue, backpressure, shutdown
  drain, health endpoints, heartbeat, and Prometheus metrics.
- Provisioned Prometheus and Grafana health dashboard.
- Replay modes `max`, `realtime`, `step`, and `xN`.
- Narrow MV3 browser bridge with exact origin allowlists, iframe injection,
  targeted header-mapped row acquisition, per-document identity, heartbeat,
  persistent bounded retry outbox, acknowledgement counters, and the
  evidence-backed visible EURUSD quote path.
- WebSocket discovery disabled by default, explicit supervised enablement,
  client/server redaction, and no last-frame persistence.
- GitHub Actions for format, lint, types, Python/extension tests, manifest safety,
  real Redis/TimescaleDB integration, and secret scanning.
- Simulated fixtures for edge-case behavior plus a sanitized live visible-DOM
  fixture for the observed collection contract.

## Security review

All host services bind to loopback. Extension permissions are allowlisted and do
not use `<all_urls>`. The bridge token is random, ignored, stored mode `0600`, and
was rotated before live validation. No password, MFA code, cookie, browser token,
account identifier, balance, profile, or order-entry value was captured. No Buy,
Sell, Close, Modify, Cancel, or New Order control was used.

## Known limitations

- Provider wire-level timestamps, sequence, heartbeat, and full/partial semantics
  remain unavailable behind the binary terminal codec.
- The visible DOM path depends on the terminal continuing to expose an EURUSD row
  with exact Symbol, Bid, and Ask columns.
- Every live tick carries a timestamp-availability warning by design.
- The local Grafana development password must be changed outside local development.
- UUID4 remains in use because the selected standard runtime does not expose UUIDv7.

## Milestone conclusion

The repository now proves the smallest trustworthy real-data path requested by
Milestone 1: authenticated IC Markets EURUSD display, evidence-based collection,
raw preservation, deterministic normalization, Redis live state/streams,
TimescaleDB history, replay, tests, and parallel health monitoring. Trading
functionality and all out-of-scope data sources remain intentionally absent.

The event contract explicitly records `source=VISIBLE_DOM`,
`observation_level=DISPLAY_QUOTE`, and `is_provider_tick=false`. Browser delivery
uses an acknowledged, idempotent outbox; browser connection and feed freshness are
independent health signals.
