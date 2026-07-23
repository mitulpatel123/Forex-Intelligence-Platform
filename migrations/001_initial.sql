CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS raw_provider_events (
  raw_event_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  adapter_instance TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  instrument TEXT,
  received_time TIMESTAMPTZ NOT NULL,
  provider_time TIMESTAMPTZ,
  payload_content_type TEXT NOT NULL,
  payload TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  redaction_status TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_time TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (raw_event_id, received_time)
);
SELECT create_hypertable(
  'raw_provider_events', by_range('received_time'), if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS price_ticks (
  event_id TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  provider TEXT NOT NULL,
  adapter_instance TEXT NOT NULL,
  instrument TEXT NOT NULL,
  bid NUMERIC(20,10) NOT NULL,
  ask NUMERIC(20,10) NOT NULL,
  mid NUMERIC(20,10) NOT NULL,
  spread NUMERIC(20,10) NOT NULL,
  spread_pips NUMERIC(20,5) NOT NULL,
  pip_size NUMERIC(20,10) NOT NULL,
  provider_event_time TIMESTAMPTZ,
  received_time TIMESTAMPTZ NOT NULL,
  normalized_time TIMESTAMPTZ NOT NULL,
  sequence BIGINT,
  snapshot BOOLEAN NOT NULL,
  changed_fields TEXT[] NOT NULL,
  quality_status TEXT NOT NULL,
  quality_flags TEXT[] NOT NULL,
  raw_event_id TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  PRIMARY KEY (event_id, received_time)
);
SELECT create_hypertable('price_ticks', by_range('received_time'), if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS data_quality_events (
  quality_event_id TEXT NOT NULL,
  related_event_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  instrument TEXT NOT NULL,
  severity TEXT NOT NULL,
  rule_id TEXT NOT NULL,
  classification TEXT NOT NULL,
  action TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  timestamp TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (quality_event_id, timestamp)
);
SELECT create_hypertable(
  'data_quality_events', by_range('timestamp'), if_not_exists => TRUE
);

CREATE TABLE IF NOT EXISTS adapter_heartbeats (
  adapter_instance TEXT NOT NULL,
  adapter_state TEXT NOT NULL,
  last_provider_message TIMESTAMPTZ,
  last_valid_tick TIMESTAMPTZ,
  reconnect_count INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT,
  timestamp TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (adapter_instance, timestamp)
);
SELECT create_hypertable(
  'adapter_heartbeats', by_range('timestamp'), if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS raw_provider_time_idx
  ON raw_provider_events (provider, received_time DESC);
CREATE INDEX IF NOT EXISTS raw_content_hash_idx
  ON raw_provider_events (content_hash, received_time DESC);
CREATE INDEX IF NOT EXISTS tick_instrument_time_idx
  ON price_ticks (instrument, received_time DESC);
CREATE INDEX IF NOT EXISTS tick_provider_time_idx
  ON price_ticks (provider, received_time DESC);
CREATE INDEX IF NOT EXISTS tick_event_lookup_idx
  ON price_ticks (event_id);
CREATE INDEX IF NOT EXISTS quality_rule_time_idx
  ON data_quality_events (rule_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS quality_related_event_idx
  ON data_quality_events (related_event_id, timestamp DESC);

