# NEXOLAB Blockers

Updated: 2026-08-18

## Autonomous Sprint selection — not blocked

Issue #546 / PR #547 is completed and merged as product baseline `ef9d69b63abecee39ff7c120ed9d11ff40082a36`.

The post-merge Ready audit identifies exactly one open product Issue carrying `status:ready`: **#548 — Add GitHub-aware safe Raspberry Pi update orchestration**. The previous `hard_blocked_no_ready_work_package` state is no longer valid.

State-only Issue #553 is the active reconciliation package and does not add product/runtime scope. After it merges, autonomous work proceeds to #548.

## Issue #546 — completed; no implementation blocker

Equipment Map Add/Replace now use the canonical hierarchical `TelemetryPointSelector`. Explicit workspace-owned organization scope is passed through the canonical editor path; no second global security-credential authority remains in the selector component.

Exact implementation head `fcf64d0fa842293facbc9762a85446f8898b43e2` was GREEN in CI #3437, Refrigeration Browser #1858, Authenticated Dashboard #1967, Offline Bundle #1371, Security Browser #1192, Acquisition Scale #174 and Disaster Recovery Browser #832.

No Raspberry Pi deployment or new hardware acceptance was required or claimed.

## Issue #548 — Ready, with deployment boundary

#548 is software-Ready and may extend the existing version-management control plane, update policy/status, host-side GitHub discovery, systemd scheduling and truthful progress UX.

However, the current Raspberry Pi **deployment capacity preflight remains blocked**. Therefore software implementation and non-mutating fixture/browser/offline verification may proceed, but no production/site activation may bypass the existing capacity, signing-key, backup, schema, package or authorization gates.

GitHub must remain an optional update-plane dependency; core `LOCAL_LAN` runtime must continue without internet.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified: read-only FC03 R7:R8 decoding, `0.01 kWh` scale, display correlation and monotonic growth under load.

Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #444 — controlled Raspberry Pi runtime acceptance blocked

Issue #444 software remains verified. Final `LOCAL_LAN` runtime acceptance is blocked by deployment-capacity preflight and signing-key authorization boundaries.

## Deployment capacity — operational blocker before next redeploy

The currently running Raspberry Pi runtime remains healthy on accepted/deployed product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0` with deployment evidence `runtime/deployments/20260817T074249Z`.

The next controlled redeploy remains stopped before mutation:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
