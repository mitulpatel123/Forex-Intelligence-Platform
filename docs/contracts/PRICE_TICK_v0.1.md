# PRICE_TICK v0.1

`PRICE_TICK` is a complete, validated EUR/USD quote. Decimal fields serialize as
strings. `mid=(bid+ask)/2`, `spread=ask-bid`, `spread_pips=spread/0.0001`.
Snapshots require both sides. A partial is published only after safe same-session
reconstruction and records exactly which side changed. UTC provider, receipt, and
normalization timestamps remain distinct.

`source`, `observation_level`, and `is_provider_tick` distinguish a rendered
display update from a provider-native tick. The Milestone 1 live bridge emits
`source=VISIBLE_DOM`, `observation_level=DISPLAY_QUOTE`, and
`is_provider_tick=false`; it does not claim wire-level tick completeness.

Quality is one of `GOOD`, `WARNING`, `BAD`, `DUPLICATE`, `LATE`, `OUT_OF_ORDER`,
`STALE`, or `UNPARSEABLE`; invalid events do not produce this contract.
