# Security

All host ports and collector services bind to loopback. The discovery endpoint
requires a random 256-bit-equivalent URL-safe token stored in `.local/bridge-token`
with mode 0600 and in extension-local storage; it is never committed. Do not paste
provider passwords, MFA codes, cookies, session tokens, or account data anywhere.

The extension uses Manifest V3, local bundled code, `storage` plus `alarms` only, no
`<all_urls>`, a seven-origin evidence-based terminal allowlist, a 256 KiB limit,
strict channel/origin validation, and recursive/token-pattern redaction. Normal
collection targets exact visible Symbol/Bid/Ask columns. Binary discovery is OFF by
default and must be enabled explicitly. Discovery payloads are redacted again by the
collector before raw storage; the collector never trusts a client-side
`SANITIZED` claim. The extension contains no trade-control code. Authorization
headers and cookies are never inspected.

`.env`, `.local`, data captures, logs, profiles, keys, and secrets are ignored.
The local Grafana default password must be changed outside local development.
