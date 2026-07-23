# Milestone 2 report

## Scope and baseline

- Milestone 1 baseline commit: `6372a7ab236b494eb181cb1d5cec13430f93d3da`
- Frozen tag: `milestone-1-live-eurusd` (verified unchanged at the baseline commit)
- Branch: `agent/milestone-2-four-pair-display-quotes`
- Feeds: EURUSD, GBPUSD, USDJPY, AUDUSD
- Qualification: all four are visible `DISPLAY_QUOTE` feeds, not provider-native
  ticks

Milestone 2 adds a canonical registry and generators, frozen v0.1/v0.2 compatibility,
generic four-pair adapter and DOM capture, fair persistent browser delivery, fair
collector queues, additive storage migration, four current/health Redis keys,
per-pair health/metrics/UI, replay/load/smoke coverage, and documentation.

The review baseline `c5c9c5854f8fbdd35dda8e64f1ca79512e93291c` predates the
timestamp/provenance hardening documented below.

## Contract, registry, and migration

`PRICE_TICK` v0.1 was not redefined. New observations use v0.2 with registry-derived
base/quote currencies and pip sizes. A discriminated union reads both versions.
Migration `003_price_tick_v02_currencies.sql` adds nullable currency columns and one
justified query index. It does not rewrite history.

Migration `004_local_pipeline_timestamps.sql` stores browser observation,
server-generated collector receipt, post-validation normalization, and
database-generated creation timestamps separately. It also stores strict
per-document/per-pair observation sequence and three local delay measurements.
Visible observations always retain null provider time/provider sequence.

## DOM and fairness design

The observer maps exact headers, discovers one target per pair within bounded work,
isolates ambiguity/missing/malformed rows, and reacquires replacements on a 100 ms
bounded schedule. Its acquisition watcher also reacts when initially empty price
cells hydrate as text. It emits only the pair that changed.

The persistent outbox reserves per-group capacity, persists stable IDs, uses capped
exponential retry, keeps strict pair FIFO by never bypassing a retrying group head,
and selects groups round-robin. The collector
uses bounded per-pair FIFO queues with round-robin consumption and a 250 ms
backpressure limit.

## Automated evidence

Commands:

```text
make check-generated
make format
make lint
make typecheck
make test
make integration-test
make smoke
make load-test
make secret-scan
```

Current local results:

- Python unit/contract/adapter/queue: 59 passed
- Extension/manifest/DOM/outbox: 42 passed
- Real Redis/TimescaleDB integration/replay: 4 passed
- Smoke: passed
- Mixed load: 5,000 processed, 0 dropped, all four pairs processed, no starvation
- Secret scan: passed locally
- GitHub Actions hardening result: all gates passed in run
  `30049575096` on reviewed implementation head
  `9bdf96ebe0f86662cbadcca14e6948a5a5e6bea6`

Mixed-load distribution was EURUSD 40%, GBPUSD 25%, USDJPY 20%, AUDUSD 15%.
It is a deterministic local display-quote pipeline workload, not provider-native
HFT performance. The final pre-PR run reported maximum pair queue depths 6/4/3/3
and p99 latency below 1.2 ms for every pair; exact values vary by machine.

Replay normalized two events per pair with only expected timestamp-unavailable
warnings. The legacy four-record v0.1-era fixture remains replayable (three valid,
one intentionally invalid).

## Live validation

The hardened final live run used the rebuilt extension continuously for 30 minutes
38 seconds, from `2026-07-23T22:51:34Z` through `2026-07-23T23:22:12Z`.
The exact reconciliation window used the clean counter baseline captured at
`2026-07-23T22:52:09Z` and the settled Prometheus/TimescaleDB snapshot at
`2026-07-23T23:22:29Z`.

| Pair | Produced | Acknowledged | Unique raw | Normalized | Retries | Drops/rejections/backend drops | Max pending | Max collector depth | Max delivery delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 307 | 307 | 307 | 307 | 6 | 0/0/0 | 1 | 1 | 31.528 s |
| GBPUSD | 445 | 445 | 445 | 445 | 6 | 0/0/0 | 11 | 1 | 31.532 s |
| USDJPY | 486 | 486 | 486 | 486 | 6 | 0/0/0 | 1 | 1 | 31.529 s |
| AUDUSD | 375 | 375 | 375 | 375 | 0 | 0/0/0 | 1 | 1 | 0.111 s |

The extension's durable counters contained pre-baseline rejection history from an
older loaded build. The table reports deltas from the clean hardened baseline;
during this final window drops and rejections did not increase. Pending repeatedly
returned to zero, including after the controlled outage. Backend invalid,
duplicate, out-of-order, stale-quality, and queue-drop counters remained zero.

The controlled collector outage ran for approximately 20 seconds. EURUSD, GBPUSD,
and USDJPY each recorded six retry attempts and drained in strict pair FIFO order.
AUDUSD did not change during the outage and therefore correctly had no queued
retry. Durable raw/normalized equality, unique IDs, and monotonic observation
sequences were preserved after restart.

All 1,613 rows in the settled reconciliation snapshot had
`provider_event_time=null`, provider `sequence=null`,
`source=VISIBLE_DOM`, `observation_level=DISPLAY_QUOTE`, and
`is_provider_tick=false`. All local timestamp and delay columns were populated and
there were no negative delays. Browser-to-collector p50/p95/p99 delays in
milliseconds were:

| Pair | p50 | p95 | p99 |
| --- | ---: | ---: | ---: |
| EURUSD | 6.171 | 45.540 | 57.622 |
| GBPUSD | 6.208 | 51.127 | 18041.467 |
| USDJPY | 6.119 | 46.773 | 24876.554 |
| AUDUSD | 6.106 | 44.209 | 66.748 |

The expected long-tail GBPUSD/USDJPY values came from delayed outbox delivery
during the controlled collector outage. Normal medians remained close to 6 ms.

The two-window active-source test held two eligible sources for every pair beyond
the lease timeout while one source remained active. In a sampled interval,
active normalized increments and standby-suppressed increments matched exactly:
EURUSD 6/6, GBPUSD 6/6, USDJPY 7/7, and AUDUSD 4/4. Closing the confirmed active
window transferred all four leases to the standby tab. In the first post-failover
sample the new active document stored 28/59/13/29 unique raw and normalized rows
for EURUSD/GBPUSD/USDJPY/AUDUSD respectively, with zero provenance, duplicate, or
ordering violations. Observation sequence continued from the values already
assigned while that document was standby; it remained strictly increasing.

The following earlier soak is retained only as historical evidence from the
pre-hardening PR head.

The earlier pre-hardening soak ran for 30 minutes 10 seconds, from
`2026-07-23T20:36:50Z` through `2026-07-23T21:07:00Z`. All values below are deltas
from the captured soak baseline, so the 879 legacy Milestone 1 outbox records purged
before the soak are excluded.

| Pair | Produced | Acknowledged | Unique raw | Normalized | Retries | Drops/rejections/backend drops | Max pending | Max collector depth | Max delivery delay |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| EURUSD | 361 | 361 | 361 | 361 | 6 | 0/0/0 | 17 | 1 | 31.533 s |
| GBPUSD | 523 | 523 | 523 | 523 | 6 | 0/0/0 | 13 | 1 | 31.537 s |
| USDJPY | 408 | 408 | 408 | 408 | 6 | 0/0/0 | 5 | 0 | 31.536 s |
| AUDUSD | 334 | 334 | 334 | 334 | 6 | 0/0/0 | 6 | 1 | 31.539 s |

Pending settled to zero. Durable tick IDs had zero duplicates. Backend invalid,
duplicate, out-of-order, stale-quality, and queue-drop counters were zero for every
pair. Every normalized row carried the expected provider-timestamp-unavailable
warning; rollover spread/jump warnings were non-dropping quality warnings.

The 30-second monitor sampled 9/8/13/11 contiguous observer-stale intervals for
EURUSD/GBPUSD/USDJPY/AUDUSD respectively, plus one controlled AUDUSD missing
interval. Ambiguous intervals were zero. Most of the longer all-pair stale samples
occurred during the 21:00Z broker rollover pause; the health model stayed degraded
instead of falsely claiming fresh quotes, and sporadic pair updates recovered
independently.

During the soak the collector was stopped. The monitor captured 31 pending at one
heartbeat; Prometheus captured per-pair maxima of 17/13/5/6. After restart, strict
pair-head FIFO drained the backlog, each pair recorded six retries, pending returned
to zero by the next monitor sample, and raw-to-normalized reconciliation remained
exact with no durable duplicates or out-of-order suppressions.

For pair isolation, AUDUSD was temporarily marked hidden in the rendered DOM.
AUDUSD alone became `MISSING`; the other three acknowledgement counters continued
advancing. Removing the marker reacquired AUDUSD and returned it to `READY`.
Fixture-based conflicting-duplicate ambiguity isolation also passed without
dangerous terminal manipulation.

## Security

Ingestion remains loopback/token protected. The extension has no broad host access,
trade permission, account-control code, credential access, or external code. Normal
capture reads only exact visible quote cells. Discovery remains supervised, bounded,
double-redacted, and OFF by default.

No trading or account controls were accessed during implementation or automated
or live validation.

## Timestamp and multi-source hardening

The collector allowlists quote values and overwrites all provenance qualifiers, so
client claims cannot turn a visible DOM row into a provider tick or supply provider
or collector timestamps. `received_at` remains a compatibility alias for
`browser_observed_at` only. Configurable quality rules flag negative/excessive
delivery delay, browser wall-clock adjustment, and missing/non-increasing sequence.

Deduplication is a bounded TTL/LRU cache and is cleared with expired document
sessions. A per-pair active-source lease prevents two open terminal tabs from
double-normalizing quotes; standby messages are deterministically acknowledged and
suppressed, with identity-safe health and failover visibility.

## Limitations and recommended Milestone 3

The visible rows expose no provider timestamp, provider sequence, or provider-native event
completeness. A browser DOM change may require observer maintenance. Milestone 3
should add downstream analytics only after preserving v0.2 compatibility,
per-pair fairness, reconciliation, and display-quote qualification.
