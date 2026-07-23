ALTER TABLE raw_provider_events
  ADD COLUMN IF NOT EXISTS browser_observed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS collector_received_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS database_created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS document_session_id TEXT,
  ADD COLUMN IF NOT EXISTS observation_sequence BIGINT,
  ADD COLUMN IF NOT EXISTS browser_to_collector_delay_ms DOUBLE PRECISION;

ALTER TABLE price_ticks
  ADD COLUMN IF NOT EXISTS browser_observed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS collector_received_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS database_created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ADD COLUMN IF NOT EXISTS document_session_id TEXT,
  ADD COLUMN IF NOT EXISTS observation_sequence BIGINT,
  ADD COLUMN IF NOT EXISTS browser_to_collector_delay_ms DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS collector_processing_delay_ms DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS total_local_pipeline_delay_ms DOUBLE PRECISION;

UPDATE raw_provider_events
SET
  browser_observed_at = received_time,
  collector_received_at = received_time,
  database_created_at = created_time
WHERE browser_observed_at IS NULL
  AND payload::jsonb ->> 'observation_source' = 'visible_dom';

UPDATE price_ticks
SET
  browser_observed_at = received_time,
  collector_received_at = received_time,
  database_created_at = normalized_time
WHERE observation_level = 'DISPLAY_QUOTE'
  AND browser_observed_at IS NULL;

CREATE INDEX IF NOT EXISTS raw_document_observation_order_idx
  ON raw_provider_events (document_session_id, instrument, observation_sequence);
CREATE INDEX IF NOT EXISTS tick_document_observation_order_idx
  ON price_ticks (document_session_id, instrument, observation_sequence);
