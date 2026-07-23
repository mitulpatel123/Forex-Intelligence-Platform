# ADR-001: IC Markets collection method

Status: **accepted for Milestone 1**

## Context

Authenticated discovery confirmed that IC Markets embeds MetaTrader 5 in a
cross-origin terminal iframe. The terminal connects to
`wss://<terminal-host>/terminal`, sets `binaryType = "arraybuffer"`, and renders
changing EURUSD bid/ask values in Market Watch.

Structured browser-received messages were the preferred source because they can
preserve provider ordering and timestamps. The observed transport uses the
terminal's binary provider codec, however, and contains no safe literal EURUSD
candidate. Broad binary capture could include unrelated account/session material.
Reverse engineering or bypassing the codec is outside the security rules.

## Decision

Use a narrow browser bridge that observes only the visible EURUSD Market Watch row.
The observer is injected only into evidenced IC Markets wrapper/MT5 origins, emits
only when the displayed bid/ask changes, validates the pair before transmission,
and sends it to an authenticated loopback collector.

Model each visible pair as a snapshot. Keep `provider_event_time` and `sequence`
null because the rendered row exposes neither. Use browser observation time only as
the receipt/ordering time and publish the explicit
`PROVIDER_TIMESTAMP_UNAVAILABLE` quality warning.

Retain the bounded WebSocket candidate observer for future evidence, but do not
persist broad binary frames or claim an unobserved provider schema.

## Consequences

The milestone obtains a real, validated EURUSD vertical slice without interacting
with trading controls or collecting account data. Raw sanitized observations,
normalized ticks, Redis state/streams, TimescaleDB history, and health metrics are
available.

This method cannot prove provider-side sequence, timestamps, heartbeat semantics,
or whether the wire protocol uses partial updates. Those limitations are explicit
and are not repaired with guessed values. UI structure changes can break capture,
so popup state, feed staleness, tests, and operational checks remain required.
