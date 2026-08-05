# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `da9bda46c320e2de6fd52e2136fdcfa368f00982`
Active Work Package: Issue #269 — operator-safe Settings workspace
Branch: `feat/269-operator-safe-settings`
Pull Request: #270 — ready-transition checkpoint
Verified source head: `434224191f914e5ca884ac838a2ce66e4a30f6ea`
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for source implementation, authenticated browser and disconnected-runtime evidence; physical Raspberry Pi and RS-485 hardware remain explicitly unverified.

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
- `/equipment` — authenticated organization-wide Equipment and metrology registry.

Verified in PR #270 and pending merge:

- `/settings` — authenticated operator-safe organization context, sanitized runtime diagnostics, explicit configuration states, versioned browser-local presentation preferences and canonical operational navigation.

Remaining placeholder routes on merged `main`:

- `/cameras` — queued local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #269 verified outcome

The source implementation on `434224191f914e5ca884ac838a2ce66e4a30f6ea` provides:

- active organization, identity, roles and effective permissions from the existing security-session contract;
- sanitized `LOCAL_LAN`, data/auth-mode, API, WebSocket and browser-origin diagnostics;
- ready, incomplete and unsafe configuration states without page crashes;
- versioned validated browser-local presentation preferences with malformed-storage recovery and reset;
- canonical links to Nodes, Equipment, Refrigeration, Alerts and Reports;
- explicit unsupported-configuration boundaries;
- zero backend mutation requests in focused authenticated browser acceptance;
- no universal settings API, database migration, dependency upgrade, device write or production cutover.

Exact-source verification:

- CI `30953948950` GREEN;
- Authenticated Dashboard Acceptance `30953948970` GREEN;
- Refrigeration Browser Acceptance `30953948956` GREEN;
- Offline Bundle `30953948928` GREEN;
- focused source diff: 13 files;
- inline review threads: zero;
- submitted reviews: zero.

## Runtime, offline and hardware evidence

```text
software verified; authenticated browser verified; disconnected bundle startup/update/rollback verified; physical Raspberry Pi and RS-485 hardware unverified
```

The Offline Bundle proved clean-host archive loading, container egress blocking, disconnected startup with pulls disabled, persistent-data preservation through update/rollback and evidence capture. No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used.

## Next action

Validate the state-only head, confirm it changes only `.project/**`, repeat the review and focused-diff audit, update PR #270 summary and mark the PR Ready without merging.
