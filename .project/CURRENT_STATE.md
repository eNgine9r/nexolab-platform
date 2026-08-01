# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `d42d163c40d8ceeee086af3d188661dfdd2b33a7`  
Active Work Package: Issue #210 / PR #213  
Next Ready after #210: Issue #199  
Status confidence: high for repository and software-CI boundaries; partial for the affected PC, actual-host recovery and hardware acceptance.

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
- PR #209 hardened Device Agent supply-chain evidence and merged as `ee950e632702135231f1f4349e87529b39d16181`.
- PR #207 completed durable central telemetry ingestion and merged as `5851955ea9a38a9068bbab1eb0c9701722c028c5`.
- Post-merge source-of-truth state is `d42d163c40d8ceeee086af3d188661dfdd2b33a7`.

## Issue #210 / PR #213

The operator screenshot shows the live dashboard blocked at `NEXOLAB Security Gate` with a generic protected-session request failure.

Verified repository behavior before correction:

- `DashboardShell` labelled both real HTTP 403 and browser transport/configuration failures as `Доступ до dashboard відхилено`;
- all thrown session `fetch` failures collapsed into one `REQUEST_FAILED` message;
- `AUTH_MODE=disabled` already returns a valid local administrator session;
- the browser calls `${NEXT_PUBLIC_NEXOLAB_API_BASE_URL}/api/v1/auth/session` directly;
- a remote browser cannot use `127.0.0.1` to reach another central host;
- the exact dashboard origin must be present in `CORS_ALLOWED_ORIGINS`.

Implemented software correction:

- bounded eight-second session request timeout;
- pre-fetch HTTPS-to-HTTP mixed-content classification;
- distinct stable codes for 401, 403, HTTP API error, invalid response, timeout and generic unreachable/origin-blocked browser failure;
- safe diagnostics containing only API origin, browser origin, endpoint path, timeout and optional HTTP status;
- a separate testable Security Gate component;
- transport/configuration failures no longer appear as authorization denial;
- retry creates a fresh request and clears stale diagnostics;
- targeted client, hook and UI tests;
- LOCAL_LAN operator diagnostics runbook.

Implementation head `6397d14ef106be637659d05619fe1b9a1a973fbb` passed general CI run `30699101280`:

- changed-file Prettier — passed;
- ESLint — passed;
- strict TypeScript — passed;
- Vitest — passed;
- production build — passed.

The current branch includes runbook and project-state changes after that implementation head. Final-head CI and affected browser acceptance are required before merge.

## Actual-host evidence boundary

The exact cause on the affected PC is not yet established. It may be:

- API service unavailable;
- frontend configured with loopback while API is on another host;
- central API bound only to loopback while the browser is remote;
- missing exact browser origin in CORS;
- HTTPS dashboard targeting HTTP API;
- another browser/network transport failure.

Use `docs/operations/dashboard-security-bootstrap.md` to collect `/health/ready`, `/api/v1/auth/session`, CORS and LAN-address evidence. Do not claim a specific root cause until those checks are run.

## Open Pull Requests

- #213 — active dashboard security bootstrap recovery.
- #192 — separate draft formatting inventory; not mixed into #210.

## Next Ready Work Package

Issue #199 — stabilize live telemetry WebSocket lifecycle and operator states. Start only after #210 merges, from the post-#210 `main`; historical PR #175 is reference-only.

## Remaining unverified areas

- affected-PC and central-host configuration evidence for #210;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
