# NEXOLAB Blockers

Updated: 2026-08-18

## Autonomous Sprint selection — not blocked

Issue #551 software fix is merged as repository product baseline `9c8f205fb17452205c5905eaea49ce878834a9c4` and moved to `status:needs-validation` pending an explicitly approved controlled Raspberry Pi LOCAL_LAN retest.

The post-merge Ready audit identifies exactly one open product Issue carrying `status:ready`: **#548 — Add GitHub-aware safe Raspberry Pi update orchestration**.

State-only Issue #555 is the active reconciliation package and does not add product/runtime scope. After it merges, autonomous software work proceeds to #548.

## Issue #551 — software resolved; runtime validation pending

The auth-aware central smoke fix is GREEN in software/offline verification:

- CI #3445;
- Telemetry service #1652;
- Offline Bundle #1376.

The corrected contract preserves positive anonymous telemetry smoke only when `AUTH_MODE=disabled`; authenticated modes require fail-closed REST 401 and `missing_bearer_token` WebSocket rejection without receiving operator credentials.

**Remaining boundary:** controlled Raspberry Pi retest has not been performed post-fix. It requires explicit deployment approval and must record exact deployed SHA, auth mode/local-auth overlay, Dashboard/API/Device Agent readiness and advancing telemetry. Until then #551 remains open `status:needs-validation` and no hardware/runtime acceptance is claimed.

## Issue #548 — Ready, with deployment boundary

#548 is software-Ready and may extend the existing version-management control plane, update policy/status, host-side GitHub discovery, systemd scheduling and truthful progress UX.

GitHub must remain update-plane only. Core `LOCAL_LAN` monitoring must operate without internet. Software implementation and fixture/browser/offline verification may proceed, but no production Raspberry Pi activation may bypass the existing package, schema, capacity, signing-key, backup, authorization or operation-lock gates.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified. Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #444 — controlled Raspberry Pi runtime acceptance blocked

Issue #444 software remains verified. Final `LOCAL_LAN` runtime acceptance remains behind controlled deployment capacity/signing safeguards and now also requires a successful post-fix #551 smoke retest.

## Deployment capacity — operational blocker before next redeploy

The currently accepted/deployed Raspberry Pi runtime remains on product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0` with accepted deployment evidence `runtime/deployments/20260817T074249Z`.

The last recorded next-redeploy preflight remains blocked:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or acceptance evidence.

The pre-fix #551 failed deployment evidence is `runtime/deployments/20260818T060358Z`; it is evidence of the old smoke mismatch, not post-fix acceptance.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #551 post-fix controlled Raspberry Pi LOCAL_LAN retest;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
