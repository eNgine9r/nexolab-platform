# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `2f3c1ebcff3d19558ed4d2b5818f7bdd48b0dfae`
Active Work Package: Issue #269 — operator-safe Settings workspace
Planned branch: `feat/269-operator-safe-settings`
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

Remaining placeholder routes on `main`:

- `/settings` — active Issue #269;
- `/cameras` — queued local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #267 merged outcome

PR #268 was squash-merged into `main` as `2f3c1ebcff3d19558ed4d2b5818f7bdd48b0dfae` after the final audit confirmed:

- exact head `b40faeb7999acea0f3e3ae2105bbd77b122add2d`;
- branch not behind `main`;
- 15 focused files;
- zero inline review threads;
- zero submitted reviews;
- CI `30929890208` GREEN;
- Authenticated Dashboard Acceptance `30929890332` GREEN;
- Refrigeration Browser Acceptance `30929890463` GREEN;
- Offline Bundle `30929890230` GREEN.

The merged `/equipment` route provides:

- normalized refrigeration equipment, temperature-controller, energy-meter and physical-sensor asset classes;
- deterministic sorting, aggregate counters and URL-backed filters;
- bounded per-chamber loading with stale-result suppression and partial-failure isolation;
- authenticated organization-scoped runtime without silent demo fallback;
- category-aware read-only details and canonical refrigeration navigation;
- explicit absence of unsupported calibration dates, certificates, laboratory and uncertainty;
- browser evidence for 287 organization-scoped assets and zero mutation requests;
- no backend schema, dependency, Modbus or hardware change.

## Active Issue #269 boundary

The `/settings` route is currently a pure `PlatformPlaceholderScreen`. Repository inventory confirms:

- the existing authenticated session contract provides identity, organizations, roles and permissions;
- client-visible runtime configuration already provides data mode, auth provider and API/WebSocket endpoints;
- no `/api/v1/settings` endpoint or persisted universal settings model exists;
- no safe generic mutation contract exists for organization, nodes, devices, retention, security or deployment.

Issue #269 will therefore deliver an operator-safe workspace composed from existing read-only contracts:

- active organization and operator context;
- sanitized runtime/deployment diagnostics;
- explicit ready/incomplete/unsafe configuration states;
- versioned browser-local presentation preferences only;
- canonical links to existing operational workflows;
- honest unsupported-configuration boundaries.

It must not expose secrets or add node/device/Modbus, retention, backup, TLS, DNS, VPN, membership or production mutations.

## Runtime, offline and hardware evidence

```text
software verified; authenticated browser/API/PostgreSQL verified; disconnected runtime verified; physical Raspberry Pi and RS-485 hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used for Issue #267.

## Next action

Create `feat/269-operator-safe-settings` from the updated `main`, open one focused draft Pull Request and implement Issue #269 through the standard targeted-test, CI and authenticated-browser acceptance sequence.
