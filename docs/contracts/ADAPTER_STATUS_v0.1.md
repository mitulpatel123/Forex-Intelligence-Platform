# ADAPTER_STATUS v0.1

Adapter status contains instance/state, connection and reconnect counts, last
provider message and valid tick, optional stable error code, human summary, and UTC
timestamp. It reports `CONNECTED` while validated live ticks are fresh, `DEGRADED`
when the latest tick is stale, and `BLOCKED_BY_PROVIDER_DISCOVERY` before the first
validated live quote.
