# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `729139a20b2bd5464aca2291dc4002f514896eee`  
Next Ready Work Package: Issue #199  
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
- PR #213 restored actionable dashboard security bootstrap diagnostics and merged as `729139a20b2bd5464aca2291dc4002f514896eee`.

## Issue #210 completed outcome

The dashboard security bootstrap remains fail-closed but no longer presents every browser transport or configuration failure as an authorization denial.

Implemented behavior:

- HTTP 401 remains `AUTHENTICATION_REQUIRED`;
- HTTP 403 remains `ACCESS_DENIED`;
- other API failures use `SESSION_API_ERROR`;
- invalid contracts use `INVALID_RESPONSE`;
- bounded requests use `SESSION_REQUEST_TIMEOUT`;
- HTTPS-to-HTTP configuration uses `SESSION_MIXED_CONTENT`;
- generic browser fetch failure uses `SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED` without claiming one unproven cause;
- safe diagnostics contain API origin, browser origin, endpoint path, timeout and optional HTTP status only;
- retry clears stale diagnostics and issues a fresh request;
- no token, cookie, password or private key is rendered;
- no demo fallback, wildcard CORS or authentication bypass was introduced.

## Final verification

Final PR head `a4318330bdce12a0b32e48cf2efb2f705fe8767a` passed all nine triggered workflows:

- CI — `30699767308`;
- Security Browser Acceptance — `30699767347`;
- Authenticated Dashboard Acceptance — `30699767325`;
- Telemetry Service — `30699767351`;
- Test Sessions Browser Acceptance — `30699767312`;
- Reports Browser Acceptance — `30699767326`;
- Rendered Reports Browser Acceptance — `30699767342`;
- Alerts Browser Acceptance — `30699767319`;
- Nodes Browser Acceptance — `30699767314`.

CI covered changed-file Prettier, ESLint, strict TypeScript, all Vitest suites and production build. Controlled browser acceptance covered JWT, RBAC, immutable audit, authenticated REST/history and WebSocket dashboard behavior.

## Actual-host evidence boundary

The exact original affected-PC cause remains unverified. It may still require correction of:

- API service availability;
- loopback versus central-host LAN address;
- central API bind address or firewall route;
- exact `CORS_ALLOWED_ORIGINS` value;
- HTTP/HTTPS and WS/WSS scheme compatibility;
- frontend rebuild or restart after `NEXT_PUBLIC_*` changes.

Use `docs/operations/dashboard-security-bootstrap.md` and return only safe outputs for `/health/ready`, `/api/v1/auth/session`, the CORS response header and endpoint origins. Do not provide tokens, passwords, cookies or private keys.

## Open Pull Requests

- #192 — separate draft formatting inventory; not mixed into product work.

## Next Ready Work Package

Issue #199 — stabilize live telemetry WebSocket lifecycle and operator states. Start from current `main` in a dedicated feature branch. Historical PR #175 is reference-only and must not be merged or rebased wholesale.

## Remaining unverified areas

- affected-PC and central-host configuration evidence for the original Security Gate incident;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
