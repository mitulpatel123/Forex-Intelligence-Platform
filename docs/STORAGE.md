# Storage

Migration `001_initial.sql` creates TimescaleDB hypertables:
`raw_provider_events`, `price_ticks`, `data_quality_events`, and
`adapter_heartbeats`. Time, provider/instrument, event, hash, and quality-rule
indexes support verification and analysis. No retention or compression policy is
enabled; test history is preserved.

Migration `002_display_quote_provenance.sql` adds durable `source`,
`observation_level`, and `is_provider_tick` columns so a rendered display update
cannot be mistaken for a provider-native tick.

Useful checks:

```sql
SELECT instrument, received_time, bid, ask, quality_status
FROM price_ticks ORDER BY received_time DESC LIMIT 10;
SELECT rule_id, classification, count(*)
FROM data_quality_events GROUP BY 1,2 ORDER BY 3 DESC;
SELECT count(*) FROM raw_provider_events;
```

Raw payloads may contain sensitive provider content despite redaction. Raw capture
is local, ignored by Git, and should be disabled or purged according to local policy.
