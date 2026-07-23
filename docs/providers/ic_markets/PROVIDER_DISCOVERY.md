# IC Markets provider discovery

Discovery date: 2026-07-23 UTC. Target: `https://webtrader-sc.ic.com/`.

## Observed delivery path

Authenticated observation confirmed that the IC Markets wrapper embeds the selected
MetaTrader 5 terminal as a cross-origin iframe. The validated session used the
`mt503web.icmarkets.com` terminal host and displayed EURUSD in Market Watch.

The terminal's public JavaScript bundle creates:

```text
wss://<terminal-host>/terminal
```

and sets `WebSocket.binaryType = "arraybuffer"`. Live browser observation confirmed
the terminal receives and renders changing EURUSD bid/ask values. The binary
messages use the terminal's provider codec and do not expose a safe literal EURUSD
text candidate. This project does not reverse engineer encryption, bypass the
provider codec, inspect credentials, or persist broad binary traffic.

## Selected collection method

The extension injects at `document_start` into the allowlisted terminal frames.
Normal collection does not inspect WebSocket payloads. Binary/text discovery is an
explicit setting that defaults to OFF. The evidence-backed live path locates a
Market Watch table with exact Symbol, Bid, and Ask headers, acquires its unambiguous
EURUSD row once, and then observes only that row:

- the symbol must equal `EURUSD`;
- bid and ask must be visible decimal values;
- both must be positive and within an EUR/USD plausibility range;
- ask must be greater than or equal to bid;
- the pair is emitted only when bid or ask changes;
- no account, balance, order, cookie, token, or credential field is read;
- no trading control is clicked or modified.

Each observation receives a UUID and enters a bounded persistent outbox. The
service worker returns its asynchronous message promise, uses a five-second fetch
timeout, retries temporary failures with the same UUID, and removes the event only
after authenticated collector acknowledgement. Pending/retry/drop/ack counters are
visible in the popup and reported by heartbeat.

Raw storage precedes normalization. Redis current state/streams, TimescaleDB
history, Prometheus, and Grafana receive the resulting events.

## Timestamp and update semantics

The displayed Market Watch row exposes a full bid/ask pair but not a provider event
timestamp or sequence. Each changed display is therefore modeled as a full snapshot.
The browser observation time is used only for receipt and ordering. The standard
event keeps `provider_event_time = null`, `sequence = null`, quality status
`WARNING`, and flag `PROVIDER_TIMESTAMP_UNAVAILABLE`. No provider time is invented.
It is also qualified as `source=VISIBLE_DOM`,
`observation_level=DISPLAY_QUOTE`, and `is_provider_tick=false`.

Provider-level partial-update, heartbeat, and sequence semantics remain opaque
behind the binary codec. The adapter's deterministic partial, duplicate,
out-of-order, stale-state, and validation policies remain covered by replay tests.

## Live validation evidence

On 2026-07-23 the extension popup reported `receiving` while the authenticated
terminal displayed EURUSD. The validated pipeline produced:

- matching visible and normalized bid/ask values;
- immutable sanitized raw events with `capture_method=visible_dom`;
- `PRICE_TICK` v0.1 events in Redis and TimescaleDB;
- current quote updates in `latest:quote:IC_MARKETS:EURUSD`;
- no invalid, duplicate, out-of-order, or stale events during the validation window;
- a fresh/healthy feed, Prometheus target `up`, and healthy Grafana.

A reviewed market-data-only sample is committed as
`adapters/ic_markets/fixtures/live_visible_dom.jsonl`. It contains no account or
authentication data.

## Reliability and privacy controls

- Account-free IDs distinguish browser run, tab, frame, and document session.
- A two-second authenticated heartbeat separates bridge connection and observer
  readiness from quote freshness.
- Server-side recursive redaction runs even when the extension already redacted a
  supervised discovery payload.
- Normal collection never stores a last WebSocket frame in extension storage.
- The outbox is capped at 1,000 events and exposes every explicit drop.
- Collector idempotency uses the browser observation UUID, including ack-loss retry.

## Public wrapper evidence

An unauthenticated HTTP GET returned the CloudFront/S3 wrapper document. Its
SHA-256 was
`74451c722239adfc5b7e333732b8165ef5caba53f168fd5e9bbc62522b3f6b39`.
The wrapper lists the global MT5 frame hosts `mt5web`, `mt502web`, `mt503web`,
`mt504web`, `mt506web`, and `mt5demo` under `icmarkets.com`.
