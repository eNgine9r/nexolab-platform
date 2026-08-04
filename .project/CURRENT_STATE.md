# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `da9bda46c320e2de6fd52e2136fdcfa368f00982`
Active Work Package: Issue #269 — operator-safe Settings workspace
Branch: `feat/269-operator-safe-settings`
Pull Request: #270 — draft implementation Work Package
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for merged repository state and previous authenticated/offline evidence; Issue #269 implementation is not yet verified; physical hardware remains explicitly unverified.

## Product route status

Implemented on merged `main`:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment and canonical mutation workflows;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring;
- `/live` — verified universal telemetry explorer;
- `/equipment-layouts` — verified cross-asset catalog and read-only published-layout preview;
- `/equipment` — authenticated organization-wide Equipment and metrology registry, merged through PR #268.

Remaining placeholder routes on merged `main`:

- `/settings` — active Issue #269 / draft PR #270;
- `/cameras` — queued local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #267 merged outcome

PR #268 was squash-merged into `main` as `2f3c1ebcff3d19558ed4d2b5818f7bdd48b0dfae` after exact-head GREEN CI, authenticated browser, refrigeration browser and disconnected Offline Bundle checks, a 15-file focused diff and zero review threads/reviews.

## Active Issue #269 boundary

Repository inventory confirms:

- `/settings` currently renders `PlatformPlaceholderScreen`;
- `GET /api/v1/auth/session` already provides identity, organizations, roles and permissions;
- existing client runtime modules provide data mode, auth provider and API/WebSocket endpoints;
- no `/api/v1/settings` endpoint, persisted universal settings table or safe generic settings mutation contract exists.

PR #270 will therefore implement:

- active organization and operator context;
- sanitized `LOCAL_LAN`, data/auth-mode, API/WebSocket and browser-origin diagnostics;
- ready, incomplete and unsafe configuration states;
- versioned browser-local non-critical presentation preferences;
- malformed-storage recovery and reset;
- canonical links to existing operational workflows;
- explicit unsupported-configuration boundaries;
- focused tests and authenticated browser evidence with zero backend mutations.

It must not expose secrets or add organization/member, node/device/Modbus, retention, backup, TLS, DNS, VPN, deployment or production mutations.

## Runtime, offline and hardware evidence

```text
software verified for merged Issue #267; Issue #269 implementation not yet verified; physical Raspberry Pi and RS-485 hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover is permitted for Issue #269.

## Next action

Implement the typed settings diagnostics and preference domain first, add focused tests, then integrate the authenticated shell and production browser acceptance in the same focused PR #270.
