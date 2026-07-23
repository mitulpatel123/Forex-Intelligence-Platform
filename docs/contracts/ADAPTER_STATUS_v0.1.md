# ADAPTER_STATUS v0.1

Adapter status contains instance/state, connection and reconnect counts, last
provider message and valid tick, optional stable error code, human summary, and UTC
timestamp. It reports `DISCONNECTED` without a fresh browser heartbeat,
`INITIALIZING` when the observer is ready but no quote has arrived, `CONNECTED`
when both bridge and display feed are fresh, and `DEGRADED` when the bridge remains
connected but the latest display quote is stale.
