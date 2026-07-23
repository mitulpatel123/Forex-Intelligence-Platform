# IC Markets provider discovery

Discovery date: 2026-07-23 UTC. Target: `https://webtrader-sc.ic.com/`.

## Evidence and selected path

Authenticated observation confirmed that the IC Markets wrapper embeds a
cross-origin MetaTrader 5 terminal. The terminal uses an opaque binary WebSocket
provider codec. This project does not reverse engineer that codec, bypass provider
controls, inspect credentials, or retain broad binary traffic.

The evidence-backed path observes only rendered Market Watch cells for:

```text
EURUSD  GBPUSD  USDJPY  AUDUSD
```

The generic observer maps exact Symbol/Bid/Ask headers, normalizes exact symbol
text, and reads only the matching cells. It does not inspect charts, order tickets,
positions, balances, or account controls. Pair precision and broad bounds come from
the canonical instrument registry.

Hidden responsive duplicates are ignored. Identical visible duplicates are
accepted only when their quotes agree. Conflicting duplicates mark only that pair
`AMBIGUOUS`. Missing/malformed rows do not block other pairs. Row/table/document
replacement triggers bounded reacquisition.

## Semantics and qualification

Every changed displayed bid/ask is a full snapshot. The UI exposes neither a
provider timestamp nor sequence; therefore both remain null. Normalized output
keeps `PROVIDER_TIMESTAMP_UNAVAILABLE` and is qualified:

```text
source = VISIBLE_DOM
observation_level = DISPLAY_QUOTE
is_provider_tick = false
```

These feeds are not provider-native ticks and do not claim provider-level
completeness, sequencing, or latency.

## Reliability and privacy

- Account-free identity distinguishes browser run, tab, frame, and document.
- Stable UUIDs survive retry; collector idempotency handles lost acknowledgements.
- Persistent per-pair outbox groups and collector queues use fair round-robin
  service with FIFO within a pair.
- Two-second heartbeats separate browser connection from each pair's freshness.
- WebSocket discovery is OFF by default, bounded, and redacted twice when enabled.
- No last discovery frame is retained in extension storage.
- The extension contains no trading or account-control interaction.

The original Milestone 1 EURUSD evidence remains in
`adapters/ic_markets/fixtures/live_visible_dom.jsonl`. Milestone 2 adds four
sanitized pair fixtures and a mixed replay fixture; these are deterministic test
evidence, not fabricated live evidence.
