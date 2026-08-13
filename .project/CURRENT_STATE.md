# NEXOLAB Current State

Updated: 2026-08-13

Canonical `main` baseline is `4581786e8b2a9b01d1430f71ca7f3cd7ee89bd0a`
(Issue #427 / PR #428 post-#366 reconciliation).

## Active Work Package — Issue #389

Issue #389 adds administrator-only local version visibility and bounded offline
update/rollback orchestration on `feat/389-local-version-management`.

The locally verified implementation provides:

- an admin-only `/settings/system/version` workspace and API read model;
- exact-confirmation update and previous-bundle-only rollback requests;
- a locked host executor, verified catalog and bounded operation history;
- verified PostgreSQL backup before mutation and migration-before-readiness;
- exact Alembic revision, platform, manifest, schema and storage-policy checks;
- named-volume and edge-SQLite preservation, with no `compose down -v` path;
- systemd and offline bundle/install wiring;
- truthful unknown runtime state after post-mutation verification failure.

Browser acceptance used an ephemeral empty catalog. Administrator read returned
200, viewer read returned 403, direct non-admin route access was denied, and no
update/rollback mutation was requested.

## Local verification

- version-manager/verifier tests: 8/8 GREEN;
- telemetry-service version API tests: 6/6 GREEN;
- focused frontend tests: 8/8 GREEN;
- full frontend tests: 88 files / 381 tests GREEN;
- format, ESLint, strict TypeScript and lint-staged contract: GREEN;
- production build and `/settings/system/version` route: GREEN;
- host executor shell contract, shell syntax and systemd units: GREEN;
- Offline Auth: existing 4/4, persistence 1/1 and version route 1/1 GREEN;
- browser evidence: `/tmp/nexolab-389-local-auth-evidence`.

Physical Raspberry Pi update/rollback execution remains a separate acceptance
lane and is not claimed by this software checkpoint.

## Ready-work continuity

Issue #289 remains `status:needs-validation` until a separate focused #356
route-prefetch/time-to-usable slice exists and its final hardware matrix is run.
Issue #415 remains unselected; Issue #245 remains a separate Raspberry Pi lane.

## Safety boundary

No Modbus or hardware write, polling-policy change, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Core runtime remains LOCAL_LAN and offline-capable.
