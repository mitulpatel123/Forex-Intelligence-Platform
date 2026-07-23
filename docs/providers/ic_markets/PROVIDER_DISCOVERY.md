# IC Markets provider discovery

Discovery date: 2026-07-23 UTC. Target: `https://webtrader-sc.ic.com/`.

## Evidence obtained

An unauthenticated HTTP GET returned 200, `text/html`, from Amazon S3 via CloudFront.
The public document SHA-256 was
`74451c722239adfc5b7e333732b8165ef5caba53f168fd5e9bbc62522b3f6b39`.
It titles itself “MetaTrader WebTrader,” contains a version/server selection screen,
creates an iframe only after selection, and does not navigate the top-level URL.

The public source shows:

- MT4 frame pattern: `https://metatraderweb.app/trade?...`
- MT5 frame pattern: `https://<selected-public-server>/terminal?...`
- Global MT5 hosts: `mt5web`, `mt502web`, `mt503web`, `mt504web`, and `mt506web`
  under `icmarkets.com`, plus `mt5demo.icmarkets.com`.
- The default selection is MT5.

This establishes a top-level wrapper plus a cross-origin terminal iframe. It does
not establish the quote delivery protocol.

## Evidence not obtained

The session’s controlled browser failed during browser-runtime initialization before
page interaction. No authenticated login, EUR/USD selection, Network panel trace,
WebSocket frame, DOM quote, subscription, heartbeat, reconnect, timestamp, sequence,
message rate, or full-vs-partial behavior was observed. No live bid/ask comparison
was possible. The failure is a tooling blocker, not a provider conclusion.

Therefore:

- delivery mechanism: unknown;
- active socket count and endpoints: unknown;
- JSON/text/binary/compression: unknown;
- EUR/USD provider symbol ID: unknown;
- snapshot vs incremental behavior: unknown;
- chart/candle source: unknown;
- live collection status: `BLOCKED_BY_PROVIDER_DISCOVERY`.

No raw private capture exists. The committed `replay_bridge.jsonl` fixture is marked
`SIMULATED_BRIDGE_CONTRACT_NOT_PROVIDER_CAPTURE` and must not be cited as evidence.

## Capture metadata contract

When discovery resumes, place ignored raw artifacts under
`data/captures/ic_markets/` and record UTC time, exact page/frame URL, selected
instrument, method, SHA-256, redaction status, schema hypothesis, and notes. Only a
reviewed sanitized fixture may be committed.

