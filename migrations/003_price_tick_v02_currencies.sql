ALTER TABLE price_ticks
  ADD COLUMN IF NOT EXISTS base_currency TEXT,
  ADD COLUMN IF NOT EXISTS quote_currency TEXT;

CREATE INDEX IF NOT EXISTS tick_instrument_normalized_time_idx
  ON price_ticks (instrument, normalized_time DESC);
