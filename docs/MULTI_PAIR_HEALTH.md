# Multi-pair health

Browser connection and quote freshness are deliberately separate.

Per pair, `/health/components` reports target/observer readiness, last DOM
observation, last valid normalized tick and age, one-minute event rate, per-pair
outbox totals, quality counters, and status.

| Pair status | Meaning |
|---|---|
| `INITIALIZING` | Target exists or bridge is starting, but no valid tick exists |
| `HEALTHY` | Target and a fresh valid tick are present |
| `MISSING` | No unambiguous valid visible row is available |
| `AMBIGUOUS` | Conflicting visible duplicates exist for that pair |
| `STALE` | The target or latest valid tick exceeded the freshness threshold |
| `DEGRADED` | Reserved feed classification for other unhealthy conditions |

Overall adapter state:

| State | Rule |
|---|---|
| `DISCONNECTED` | Authenticated browser heartbeat is not fresh |
| `INITIALIZING` | Bridge is connected but no supported pair is ready |
| `CONNECTED` | All four pairs are `HEALTHY` |
| `DEGRADED` | Any pair is missing, ambiguous, stale, or unhealthy |

An iframe reporting `MISSING` cannot overwrite a healthy terminal document.
Conflicting ambiguity is intentionally higher priority. One stale pair never
changes another pair's last tick, counters, Redis key, or status.
