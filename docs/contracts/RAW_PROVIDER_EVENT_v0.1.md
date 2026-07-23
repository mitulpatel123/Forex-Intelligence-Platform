# RAW_PROVIDER_EVENT v0.1

The immutable raw record stores provider/adapter and connection/session identity,
optional instrument/provider time, receipt time, content type, sanitized payload,
SHA-256 content hash, channel metadata, redaction status/paths, and trace ID. It is
accepted before normalization. Discovery records may remain unmapped.

For visible-DOM observations it also stores `browser_observed_at`,
server-generated `collector_received_at`, `document_session_id`,
`observation_sequence`, and `browser_to_collector_delay_ms`. Compatibility
`received_at` means browser observation time for these display events.
`provider_event_time` remains null.
