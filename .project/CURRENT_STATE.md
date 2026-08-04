# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `d70030dd17cde1031291e9725096a0f3d292192b`
Active Work Package: Issue #267 — Equipment and metrology registry
Branch: `feat/267-equipment-metrology-registry`
Pull Request: #268 — executable scope verified; state-only exact-head gate required before ready transition
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Verified executable source head: `ad3aae9d8419d21082aabc8c19565953848671cb`
Status confidence: high for repository, authenticated browser/API/PostgreSQL, regression, review-scope and disconnected-runtime evidence; physical hardware remains explicitly unverified.

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
- `/equipment-layouts` — verified cross-asset catalog and read-only published-layout preview, merged through PR #266.

Implemented and executable-verified in PR #268:

- `/equipment` — authenticated organization-wide Equipment and metrology registry.

Remaining placeholder routes on `main`:

- `/equipment` until PR #268 merges;
- `/settings` — operator-safe Settings;
- `/cameras` — local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #267 completed product scope

PR #268 provides:

- one normalized read model for refrigeration equipment, temperature controllers, energy meters and physical sensors;
- deterministic category, identifier and name ordering;
- summary counters for all assets, refrigeration equipment, measurement devices, physical sensors and due/expired calibration risk;
- combined URL-backed search, asset-class, climate-chamber, manufacturer, lifecycle/connection and calibration filters;
- deterministic filter persistence through reload and clear navigation;
- bounded climate-chamber summary loading with cancellation, stale-result suppression and partial-failure preservation;
- category-aware read-only details without duplicating refrigeration mutation workflows;
- canonical navigation to `/refrigeration/[equipmentId]` for supported refrigeration mutations;
- authenticated organization-scoped runtime with no silent live-to-demo fallback;
- explicit loading, authentication, configuration, empty, error and retry states;
- truthful metrology boundary: the repository does not currently store calibration dates, next-due dates, certificate numbers/files, calibration laboratory or uncertainty;
- no universal asset table, dependency upgrade, database migration, backend schema change, Modbus write or hardware path.

## Exact executable verification

Verified on source head `ad3aae9d8419d21082aabc8c19565953848671cb`:

- CI `30927620394` GREEN;
- Authenticated Dashboard Acceptance `30927615108` GREEN with all five production browser flows passing;
- Refrigeration Browser Acceptance `30927615177` GREEN;
- Offline Bundle `30927620159` GREEN;
- browser evidence artifact `8899868692` captured.

The authenticated browser gate used production Next.js, FastAPI and PostgreSQL and proved:

- organization-wide total of 287 visible registry assets;
- three refrigeration lifecycle fixtures: active, maintenance and retired;
- connected, disconnected and unknown measurement-device states;
- current, due, expired and untracked physical-sensor calibration states;
- four injected failed-chamber requests remained isolated while successful assets stayed usable;
- URL-backed combined filters persisted through reload and cleared deterministically;
- read-only category-specific details rendered without fabricated metrology fields;
- canonical navigation reached `/refrigeration/66600000-0000-4000-8000-000000000001`;
- every observed registry request was authenticated, organization-scoped and GET-only;
- zero registry mutation requests were observed.

The same five-flow gate also re-verified dashboard, energy, live telemetry and Equipment Layouts. Equipment Layouts correctly derived the shared organization total of eight equipment records while retaining all five focused layout lifecycle assertions.

## Runtime, offline and hardware evidence

The disconnected Offline Bundle loaded and started the archive with container egress blocked and `--pull never`, then proved update/rollback persistence preservation without deleting named volumes.

```text
software verified; authenticated browser/API/PostgreSQL verified; disconnected runtime verified; physical Raspberry Pi and RS-485 hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used.

## Next action

Validate the exact state-only checkpoint head, perform the final review and focused-diff audit, update PR #268 verification metadata and mark PR #268 ready for review without merging it. After merge, the next queued product route is `/settings`.
