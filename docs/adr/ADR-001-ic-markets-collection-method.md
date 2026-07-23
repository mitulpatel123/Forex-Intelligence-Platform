# ADR-001: IC Markets collection method

Status: **provisional / blocked by provider discovery**

The public `webtrader-sc.ic.com` document is an IC Markets wrapper that lets the
user choose MT4 or MT5. It dynamically appends an iframe. MT4 points to a MetaTrader
web application; MT5 points to one of six public global server hosts listed in the
wrapper configuration. This makes the wrapper origin alone insufficient for feed
observation.

Decision: pursue priority 2, structured browser-received WebSocket/network messages,
because it can preserve provider values and ordering better than DOM scraping. The
MV3 observer is injected at `document_start` into only the evidenced wrapper and
global MT5 frame origins. It captures only small text frames containing an EUR/USD
candidate marker, redacts token-like strings, and sends them to authenticated
loopback raw storage. No endpoint, subscription, selector, or schema is claimed.

Until an authenticated sample is captured and matched to the visible bid/ask,
normalization remains `BLOCKED_BY_PROVIDER_DISCOVERY`; the system uses an explicitly
simulated bridge-contract fixture.

Failure modes include binary/compressed frames, symbol aliases without EUR/USD text,
sockets created before injection, provider origin changes, service-worker delivery,
schema changes, server selection, and token misconfiguration. DOM observation is
reserved for a later evidence-backed fallback.

