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
- GitHub Actions hardening result: all gates passed on
  `014113ba607bde983cc9f74f72da969053a1cc8b`

Mixed-load distribution was EURUSD 40%, GBPUSD 25%, USDJPY 20%, AUDUSD 15%.
It is a deterministic local display-quote pipeline workload, not provider-native
HFT performance. The final pre-PR run reported maximum pair queue depths 6/4/3/3
and p99 latency below 1.2 ms for every pair; exact values vary by machine.

Replay normalized two events per pair with only expected timestamp-unavailable
warnings. The legacy four-record v0.1-era fixture remains replayable (three valid,
one intentionally invalid).

## Live validation

The following soak is historical evidence from the pre-hardening PR head. It is
not claimed as final validation of the timestamp/lease changes. A new live Chrome
soak remains pending because the browser-control connection could not be
established during this implementation run; all automated and integration gates
above used the hardened code.

The definitive final-build soak ran for 30 minutes 10 seconds, from
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
