# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `da9bda46c320e2de6fd52e2136fdcfa368f00982`
Active Work Package: Issue #269 — operator-safe Settings workspace
Branch: `feat/269-operator-safe-settings`
Pull Request: pending draft creation
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for merged repository, authenticated browser/API/PostgreSQL and disconnected-runtime evidence; physical hardware remains explicitly unverified.

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

- `/settings` — active Issue #269 and feature branch started;
- `/cameras` — queued local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #267 merged outcome

PR #268 was squash-merged into `main` as `2f3c1ebcff3d19558ed4d2b5818f7bdd48b0dfae` after the final audit confirmed exact-head GREEN CI, authenticated browser, refrigeration browser and disconnected Offline Bundle checks, a 15-file focused diff and zero review threads/reviews.

The merged `/equipment` route provides a normalized authenticated read-only equipment/metrology registry without backend schema, dependency, Modbus or hardware changes.

## Active Issue #269 boundary

The `/settings` route is currently a pure `PlatformPlaceholderScreen`. Repository inventory confirms:

- the existing authenticated session contract provides identity, organizations, roles and permissions;
- client-visible runtime configuration already provides data mode, auth provider and API/WebSocket endpoints;
- no `/api/v1/settings` endpoint or persisted universal settings model exists;
- no safe generic mutation contract exists for organization, nodes, devices, retention, security or deployment.

Issue #269 will deliver an operator-safe workspace composed from existing read-only contracts:

- active organization and operator context;
- sanitized runtime/deployment diagnostics;
- explicit ready/incomplete/unsafe configuration states;
- versioned browser-local presentation preferences only;
- canonical links to existing operational workflows;
- honest unsupported-configuration boundaries.

It must not expose secrets or add node/device/Modbus, retention, backup, TLS, DNS, VPN, membership or production mutations.

## Runtime, offline and hardware evidence

```text
software verified for merged Issue #267; Issue #269 implementation not yet verified; physical Raspberry Pi and RS-485 hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover is permitted for Issue #269.

## Next action

Open one focused draft Pull Request for `feat/269-operator-safe-settings`, then implement the typed runtime-diagnostics and browser-local preference vertical slice with focused tests and authenticated browser acceptance.
