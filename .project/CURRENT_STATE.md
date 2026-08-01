# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `764c0be96652144920964f7806af493a7a0a7b1e`  
Active Work Package: Issue #199 / PR #214  
Status confidence: high for repository and software-CI boundaries; partial for actual-host and hardware acceptance.

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

## Issue #199 active outcome

Issue #199 is implemented in branch `fix/199-websocket-lifecycle` through draft PR #214.

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

## Verification in progress

Clean implementation/test candidate before project-state commits: `84ca8e9e1176746db8a2d1aa9f0a2d1b73bc0d1c`.

Evidence already obtained:

- changed-file Prettier passed;
- ESLint passed;
- strict TypeScript passed;
- the new five-test WebSocket lifecycle suite passed;
- the new three-test dashboard lifecycle suite passed;
- the preceding full Vitest run passed 174 of 176 tests; the only failures were two legacy assertions that still treated `open` as live evidence;
- those two assertions are now updated to require heartbeat evidence;
- intermediate Authenticated Dashboard Acceptance passed on the implementation branch;
- all temporary formatter and test-update workflows were removed from the final product diff.

Final-head full Vitest, production build and browser acceptance remain pending and must be GREEN before merge.

## Open Pull Requests

- #214 — active draft WebSocket lifecycle correction.
- #192 — separate draft formatting inventory; not mixed into product work.

## Next sequencing

After PR #214 is GREEN and merged, the next independent software Work Package is Issue #187 — build and prove a verified offline installation and update bundle. Issue #188 remains the following offline-authentication Work Package.

## Remaining unverified areas

- affected-PC and central-host configuration evidence for the original Security Gate incident;
- final browser/API acceptance for PR #214 on its final head;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
