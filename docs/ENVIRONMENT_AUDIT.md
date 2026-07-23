# Environment audit

Audit time: 2026-07-23 (America/New_York).

| Item | Observed |
|---|---|
| macOS | 26.5.1 (build 25F80) |
| Architecture | Apple Silicon `arm64` |
| CPU | 16 logical cores |
| RAM | 51,539,607,552 bytes (48 GiB) |
| Workspace disk | 1.8 TiB total; about 1.4 TiB free |
| Shell | `/bin/zsh` |
| Git | 2.50.1 (Apple Git-155) |
| Homebrew | 6.0.6 at audit; auto-updated during Node install |
| System Python | 3.9.6 at `/usr/bin/python3` |
| Project Python | CPython 3.12.11 managed by `uv` |
| uv | 0.8.17 |
| Node before setup | 25.2.1, non-LTS |
| Node after setup | Homebrew `node@22` 22.23.1, linked |
| Corepack / pnpm | 0.34.6 / 10.15.1 |
| Chrome | 150.0.7871.129 |
| Docker | Docker Desktop engine 29.1.3; Compose 2.40.3 |
| Local PostgreSQL | Client 14.20; servers already on ports 5432/5433 |
| Local Redis | 8.4.0 already on port 6379 |

Project containers therefore use conflict-free loopback ports 55432 and 6380.
Other observed listeners included macOS services on 5000/7000 and local developer
tools on 5037, 11434, 27017, and 41343. Docker Desktop was installed but stopped;
it was launched and its engine health was verified. No GUI software was installed.

Installation choice: reuse Docker Desktop and `uv`; install the active Node 22 LTS
formula because the pre-existing Node 25 release did not meet the project LTS policy.

