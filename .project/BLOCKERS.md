# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #548 / PR #559 — software merged, no software blocker

Issue #548 is closed with `status:done`. PR #559 is squash-merged into the accepted product baseline:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

Final PR exact head `76120bef1108086fdc1648cddbcf9bd293502e6e` passed all 13 triggered workflows. The software/security/offline boundary is accepted; Raspberry Pi runtime acceptance remains unverified.

## State reconciliation — completed

Issue #571 is closed with `status:done`. PR #572 merged the focused post-#548 state reconciliation at `0339bef188ac482a6b77450c3b14861dc58ed29e` after exact-head CI #3550 passed.

## Raspberry Pi deployment — current hard blocker

The current Raspberry Pi remains untouched at:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Evidence remains:

`runtime/deployments/20260818T083157Z`

The next product-relevant Work Package is Issue #566: controlled deployment of the merged NEXOLAB product baseline and combined #566/#560/#548 runtime acceptance.

This is a **hard blocker waiting for separate explicit user approval** before any Raspberry Pi change, service restart, host installation or cutover.

Required runtime evidence includes:

- repository-backed local administrator login without manual auth-provider correction;
- access-token rotation continuity for Energy Monitoring/history requests;
- no recurrence of `401 invalid_bearer_token`;
- #548 automatic-update policy default OFF;
- safe manual update discovery and truthful offline/update-plane behavior;
- installed 02:00 host-local scheduler/policy state;
- version-management capacity/backup/package-validation/runtime-verification/rollback evidence where exercised;
- actual Raspberry Pi runtime identity, API/Dashboard readiness, Device Agent health and telemetry freshness.

## Deployment capacity

The latest controlled Raspberry Pi deployment preflight remains PASS:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- root filesystem was 68% used at recorded preflight.

Future deployments must run the capacity guard. Do not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Remaining evidence lanes

- #566 / #560 post-merge LOCAL_LAN deployment and token-rotation runtime acceptance;
- #444 end-to-end local user-management acceptance;
- #201 approved restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- #548 Raspberry Pi version-management acceptance as part of the approved deployment lane.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
