# Security

Collector ingestion binds to loopback and requires a random local bridge token
stored in `.local/bridge-token` with mode 0600 and in extension-local storage.
Never provide provider passwords, MFA codes, cookies, session tokens, or account
data to this project.

The Manifest V3 extension uses bundled local code, only `storage` and `alarms`,
no `<all_urls>`, an evidence-based terminal allowlist, strict origin/channel/schema
checks, and a 256 KiB payload bound. Normal capture reads only visible Symbol, Bid,
and Ask cells for the four supported pairs. It has no trade or account-control
permissions or code.

WebSocket discovery is OFF by default and is unrelated to normal four-pair
collection. When explicitly enabled for supervised diagnostics, candidates are
bounded, allowlisted, and redacted in the extension and again by the collector.
The collector never trusts a client `SANITIZED` claim. No last discovery frame is
retained in extension storage.

`.env`, `.local`, data captures, logs, profiles, keys, and secrets are ignored.
Change the local Grafana default password outside isolated development.
