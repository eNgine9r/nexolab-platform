# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `764c0be96652144920964f7806af493a7a0a7b1e`  
Active Work Package: Issue #199 / PR #214 — ready to merge  
Status confidence: high for repository, software-CI and controlled browser boundaries; partial for actual-host and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed baseline

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture and offline boundary.
- PR #206 reconciled stale Pull Requests, trackers and successor Issues.
- PR #209 hardened Device Agent supply-chain evidence.
- PR #207 completed durable central telemetry ingestion.
- PR #213 restored actionable dashboard security bootstrap diagnostics; product merge `729139a20b2bd5464aca2291dc4002f514896eee`, post-merge state baseline `764c0be96652144920964f7806af493a7a0a7b1e`.

## Issue #199 verified outcome

Issue #199 is implemented in branch `fix/199-websocket-lifecycle` through PR #214.

Implemented behavior:

- a bounded 15-second WebSocket connection-open timeout;
- browser-safe private client close codes `4000`–`4004`, including `4002` for connection timeout;
- a transport `open` event no longer proves that telemetry is live;
- `connected` is reached only after authenticated acknowledgement, heartbeat or a valid sample;
- reconnect backoff resets only after valid live evidence;
- connection, authentication, heartbeat and reconnect timers are cleaned centrally;
- credentials are resolved again for every reconnect attempt;
- terminal unauthorized, forbidden and configuration failures remain distinct;
- resume cursor and event-id deduplication remain intact;
- stale snapshots remain visible but receive stale/offline rather than live presentation.

## Verification

Verified code-and-test head: `5edad95e6fa76ab52a0dfdbcf74e8607b0bfe568`.

- CI run `30704096637` passed changed-file Prettier, ESLint, strict TypeScript, all Vitest suites and production build.
- Authenticated Dashboard Acceptance run `30704096614` passed authenticated REST/history and WebSocket dashboard behavior.
- The dedicated WebSocket lifecycle suite passed 5 tests.
- The dedicated dashboard lifecycle suite passed 3 tests.
- Legacy assertions now require heartbeat evidence rather than transport-open evidence.
- Final product diff contains eight scoped runtime/test/state files and no temporary workflow.

## Open Pull Requests

- #214 — GREEN and ready for final review/merge.
- #192 — separate draft formatting inventory; not mixed into product work.

## Next Ready Work Package

After PR #214 is merged, activate Issue #187 — build and prove a verified offline installation and update bundle. Issue #188 remains the following offline-authentication Work Package.

## Remaining unverified areas

- affected-PC and central-host configuration evidence for the original Security Gate incident;
- operator-started LOCAL_LAN browser verification outside controlled CI;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
