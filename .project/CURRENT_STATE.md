# NEXOLAB Current State

Updated: 2026-08-13

Canonical `main` is `83c77c934ed0c3356752dc11ce98247f243fa659`
(Issue #389 / PR #429 safe local version management).

## Completed Work Package — Issue #389 / PR #429

Issue #389 is closed. PR #429 was squash-merged after the exact tested head
`a12c90968c736839991b88237033ee950c9ba707` passed all 21 triggered workflows.

The merged LOCAL_LAN/offline implementation provides:

- administrator-only local version/readiness/history UI and API;
- validated bounded offline package catalog;
- exact-confirmation update and previous-bundle-only rollback requests;
- a locked, bounded host executor with no arbitrary shell surface;
- verified PostgreSQL backup before mutation;
- explicit platform/schema/storage compatibility and migration-before-readiness;
- exact post-deployment Alembic revision verification;
- named-volume and edge-SQLite preservation with no destructive downgrade path;
- truthful unknown runtime evidence after post-mutation verification failure;
- systemd, offline bundle/install and operator runbook wiring.

Local browser evidence proved administrator 200, viewer 403, explicit offline
empty-catalog state and zero update/rollback mutation. Offline Bundle #1070 also
proved clean-host transfer, blocked-egress startup and update/rollback persistent
volume preservation.

Classification: software verified; Raspberry Pi version-management acceptance
pending separately.

## Active state-only reconciliation — Issue #430

Issue #430 records the #389 merge and post-merge Ready audit in exactly four
`.project` files. No product/runtime change belongs in #430.

The fresh audit found no open `status:ready` Issue. Issue #289 remains
`status:needs-validation`: a separate focused #356 route-prefetch/time-to-usable
Work Package must be defined and verified before final physical/performance
acceptance. Issue #415 remains unselected and Issue #245 remains a separate
Raspberry Pi lane.

## Safety boundary

No Modbus or hardware write, polling-policy change, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Core runtime remains LOCAL_LAN and offline-capable.
