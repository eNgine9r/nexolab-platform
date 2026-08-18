# NEXOLAB Blockers

Updated: 2026-08-18

## Current Sprint selection — not blocked

Critical LOCAL_LAN bearer-token regression #560 is software/offline complete and merged through PR #561 as `4cf20a173c793f67b7befb239d8489977d0df4b5`.

Exact-head CI, Security Browser, Authenticated Dashboard, Offline Auth, affected shared-client browser acceptances and Offline Bundle were GREEN before merge.

The active product implementation lane remains:

**Issue #548 / draft PR #559 — Add GitHub-aware safe Raspberry Pi update orchestration.**

State-only Issue #564 is reconciling the #560 merge before #548 continues. No parallel #548 branch should be created.

## Issue #560 — post-fix Raspberry Pi runtime validation pending

This is an evidence boundary, not a software blocker.

Repository/accepted software now contains the token-rotation fix at `4cf20a173c793f67b7befb239d8489977d0df4b5`, but the deployed Raspberry Pi baseline remains `2d7740ff1cc2e638f47f2f0787a8e0516626c61e`.

Therefore the operator-observed `401 invalid_bearer_token` may still occur on the currently deployed Pi until a separately approved controlled deployment is performed. Post-fix acceptance requires keeping Energy Monitoring active through at least one complete local access-token rotation window and proving the 401 does not recur.

Do not claim post-fix Pi runtime verification from CI, browser mocks or Offline Bundle evidence.

## Deployment capacity — current blocker cleared

The 2026-08-18 controlled deployment capacity guard passed:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- post-deployment root filesystem: 68% used with about 18G available.

Future deployments must still run the same guard. Do not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #444 — no longer deployment-blocked

Issue #444 remains `status:needs-validation`.

Controlled LOCAL_LAN runtime proves local-auth overlay active, local administrator login PASS, `/api/v1/admin/users` mounted and authenticated administrator HTTP 200. Remaining validation is the actual end-to-end create/manage user path and non-admin authorization/frontend diagnostic behavior as applicable.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified. Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #560 post-fix LOCAL_LAN token-rotation runtime acceptance;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- future Raspberry Pi version-management acceptance for #548.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
