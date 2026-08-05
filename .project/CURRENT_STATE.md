# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `93e865efdadcd1f63a0c31733b98e13f8b6eb4c1`
Active Work Package: Issue #275 — post-Cameras project-state reconciliation
Branch: `chore/275-post-cameras-state`
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for merged software, authenticated browser and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Product route status

Implemented on merged `main`:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — Energy Monitoring;
- `/live` — universal telemetry explorer;
- `/equipment-layouts` — layouts catalog;
- `/equipment` — equipment and metrology registry;
- `/settings` — operator-safe Settings workspace;
- `/cameras` — authenticated truthful local camera readiness workspace.

Remaining primary placeholder/blocker:

- `/lockers` — blocked pending concrete locker inventory, read-only protocol and operator workflow. No implementation may invent production locker behavior or expose write controls.

## Cameras merge outcome

Issue #273 / PR #274 was squash-merged as `93e865efdadcd1f63a0c31733b98e13f8b6eb4c1`.

Verified source head `3b39d9e9f1a8e15c0cb66d0fd8924c25ffba390b` and state head `adc6dec1eefe043da2813b7c59be6d39aa1e1aa6` delivered:

- typed bounded camera records and explicit availability states;
- local endpoint sanitization without credentials, query strings or public hosts;
- authenticated `/cameras` shell with deterministic search and filters;
- truthful `unconfigured` production state until a real safe inventory exists;
- removal of fabricated Overview `LIVE` scenes;
- zero non-GET camera requests in focused acceptance;
- no dependency, backend schema, camera write, Modbus write or production cutover.

State-head verification:

- CI `30973948934` GREEN;
- Authenticated Dashboard Acceptance `30973948889` GREEN;
- Refrigeration Browser Acceptance `30973948945` GREEN;
- Offline Bundle `30973948909` GREEN;
- inline review threads: zero;
- submitted reviews: zero.

## Parent Issue #260 reassessment

Issue #260 remains open. Six queued placeholder page Work Packages are complete and merged. The only remaining placeholder route is `/lockers`, which is an approved blocked state because the repository has no concrete locker inventory or read-only protocol scope.

The next independent product action under #260 is a focused cross-page consistency/completeness review. Smart Lockers must remain blocked until the Product Owner supplies concrete inventory, protocol and operator outcome.

## Runtime and hardware evidence

```text
software verified; authenticated browser verified; disconnected bundle update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Next action

Validate and merge the control-only Issue #275 PR after confirming its diff contains exactly four `.project/**` files and CI is GREEN. Then create the focused cross-page consistency review Work Package under Issue #260; do not start `/lockers` implementation without concrete scope.
