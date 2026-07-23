ALTER TABLE price_ticks
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'WEB_TERMINAL',
  ADD COLUMN IF NOT EXISTS observation_level TEXT NOT NULL DEFAULT 'PROVIDER_TICK',
  ADD COLUMN IF NOT EXISTS is_provider_tick BOOLEAN NOT NULL DEFAULT TRUE;

UPDATE price_ticks AS tick
SET
  source = 'VISIBLE_DOM',
  observation_level = 'DISPLAY_QUOTE',
  is_provider_tick = FALSE
FROM raw_provider_events AS raw
WHERE raw.raw_event_id = tick.raw_event_id
  AND raw.payload::jsonb ->> 'observation_source' = 'visible_dom';
