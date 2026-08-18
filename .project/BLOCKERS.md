# NEXOLAB Blockers

Updated: 2026-08-18

## Current Sprint selection — not blocked

Critical LOCAL_LAN authentication/deployment validation is complete.

Issues #551 and #557 are closed `status:done` after successful controlled Raspberry Pi deployment on exact SHA `2d7740ff1cc2e638f47f2f0787a8e0516626c61e` with evidence `runtime/deployments/20260818T073437Z`.

The active product implementation lane is now:

**Issue #548 / draft PR #559 — Add GitHub-aware safe Raspberry Pi update orchestration.**

No parallel #548 branch should be created.

## Deployment capacity — current blocker cleared

The 2026-08-18 controlled deployment capacity guard passed:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- post-deployment root filesystem: 68% used with about 18G available.

This clears the previous capacity blocker for the accepted deployment. Future deployments must still run the same guard. Do not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #444 — no longer deployment-blocked

Issue #444 is now `status:needs-validation`.

Controlled LOCAL_LAN runtime proves:

- local-auth overlay active;
- local administrator login PASS;
- `/api/v1/admin/users` route mounted;
- authenticated administrator receives HTTP 200.

Remaining validation is the actual end-to-end create/manage user path and non-admin authorization/frontend diagnostic behavior as applicable. This is no longer blocked by auth bootstrap, deployment capacity or smoke-gate failure.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified. Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- future Raspberry Pi version-management acceptance for #548.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
