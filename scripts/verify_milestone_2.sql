-- Latest normalized display quote per supported instrument.
SELECT DISTINCT ON (instrument)
  instrument, bid, ask, spread_pips, received_time
FROM price_ticks
WHERE instrument IN ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD')
ORDER BY instrument, received_time DESC;

-- Durable row and warning counts per pair.
SELECT
  instrument,
  count(*) AS normalized_rows,
  count(*) FILTER (WHERE quality_status = 'WARNING') AS warnings
FROM price_ticks
WHERE instrument IN ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD')
GROUP BY instrument
ORDER BY instrument;

-- Delivery reconciliation: unique raw display observations against normalized rows.
SELECT
  raw.instrument,
  count(DISTINCT raw.raw_event_id) AS accepted_unique_raw,
  count(DISTINCT tick.event_id) AS normalized
FROM raw_provider_events AS raw
LEFT JOIN price_ticks AS tick ON tick.raw_event_id = raw.raw_event_id
WHERE raw.instrument IN ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD')
GROUP BY raw.instrument
ORDER BY raw.instrument;

-- Stale or missing pair analysis over the last minute.
WITH supported(instrument) AS (
  VALUES ('EURUSD'), ('GBPUSD'), ('USDJPY'), ('AUDUSD')
)
SELECT
  supported.instrument,
  max(tick.received_time) AS last_tick,
  extract(epoch FROM (now() - max(tick.received_time))) AS age_seconds
FROM supported
LEFT JOIN price_ticks AS tick USING (instrument)
GROUP BY supported.instrument
ORDER BY supported.instrument;
