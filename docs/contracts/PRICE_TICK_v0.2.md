# PRICE_TICK v0.2

`PRICE_TICK` v0.2 represents a validated display observation for one canonical FX
pair. Milestone 1 v0.1 remains frozen and readable.

Required fields:

```text
event_id, schema_version, event_type, source, observation_level,
is_provider_tick, provider, adapter_instance_id, instrument,
base_currency, quote_currency, bid, ask, mid, spread, spread_pips,
pip_size, is_snapshot, changed_fields, provider_event_time, received_at,
normalized_at, sequence, raw_event_id, raw_payload_hash, quality_status,
quality_flags, trace_id
```

Rules:

- `schema_version` is `0.2`; `event_type` is `PRICE_TICK`.
- `instrument` is exactly EURUSD, GBPUSD, USDJPY, or AUDUSD.
- currencies and pip size must match the canonical registry.
- prices are finite positive Decimals and `ask >= bid`.
- `mid = (bid + ask) / 2`.
- `spread = ask - bid`.
- `spread_pips = spread / pip_size`.
- zero spread is valid.
- visible DOM observations are full snapshots with both changed fields.
- live DOM rows use `VISIBLE_DOM`, `DISPLAY_QUOTE`, and `false`.
- absent provider time and sequence remain null; they are never inferred.
- unexpected fields are rejected.

Compatibility parsing discriminates v0.1 and v0.2 using `schema_version`.
Historical v0.1 rows are not rewritten.
