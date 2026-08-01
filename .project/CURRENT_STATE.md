# NEXOLAB Current State

Updated: 2026-08-01  
Verified product baseline: `main` at `8bcf67131ce6900b3513e840661d3cf82934c7eb`  
Next Ready Work Package: Issue #187  
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
- PR #213 restored actionable dashboard security bootstrap diagnostics.
- PR #214 stabilized the live telemetry WebSocket lifecycle and merged as `8bcf67131ce6900b3513e840661d3cf82934c7eb`.

## Issue #199 completed outcome

The dashboard now treats a WebSocket transport connection as Live only after valid application-level evidence.

Completed behavior:

- bounded 15-second WebSocket connection-open timeout;
- browser-safe private client close codes `4000`–`4004`;
- `connected` only after authenticated acknowledgement, heartbeat or a valid sample;
- reconnect backoff reset only after valid live evidence;
- centralized cleanup of connection, authentication, heartbeat and reconnect timers;
- fresh credential resolution for every reconnect attempt;
- distinct unauthorized, forbidden and configuration terminal states;
- preserved resume cursor and event-id deduplication;
- stale snapshots remain visible but receive stale/offline rather than live presentation.

## Final verification

Final PR head `921fba3f1af382f471b614ab5d2cc71952fad0db` passed:

- CI run `30704859884`: changed-file Prettier, ESLint, strict TypeScript, all Vitest suites and production build;
- Authenticated Dashboard Acceptance run `30704859869`: authenticated REST/history and WebSocket dashboard behavior;
- dedicated WebSocket lifecycle suite: 5 tests;
- dedicated dashboard lifecycle suite: 3 tests;
- final changed-file count: 8 scoped files;
- review threads: 0;
- submitted reviews: 0.

## Open Pull Requests

- #192 — separate draft formatting inventory; not mixed into product work.

## Next Ready Work Package

Issue #187 — build and prove a verified offline installation and update bundle.

Required boundary:

- produce a checksummed local OCI/application bundle;
- prove installation and update on a clean disconnected host;
- preserve persistent volumes and local laboratory data;
- keep offline operator authentication in separate Issue #188;
- do not perform production/site cutover without explicit approval.

## Remaining unverified areas

- affected-PC and central-host configuration evidence for the original Security Gate incident;
- operator-started LOCAL_LAN browser verification outside controlled CI;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
