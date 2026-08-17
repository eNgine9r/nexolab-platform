# NEXOLAB Blockers

Updated: 2026-08-17

## Issue #537 — no implementation blocker

Product Owner selected Issue #537 and the focused implementation is present in PR #538. Exact implementation head `3df744d36000d719cff02fd756e0610354b1eebc` is GREEN in CI, Authenticated Dashboard Acceptance, Refrigeration Browser Acceptance and Offline Bundle.

The former `hard_blocked_no_ready_work_package` state no longer applies to this selected Work Package. Final merge still requires the normal exact-head state/check/review audit.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified: read-only FC03 R7:R8 decoding, `0.01 kWh` scale, display correlation and monotonic growth under load.

Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance. Issue #537 deliberately fails closed on a negative cumulative delta rather than inventing rollover semantics.

## Issue #444 — controlled Raspberry Pi runtime acceptance blocked

Issue #444 software remains verified. Final `LOCAL_LAN` runtime acceptance is blocked by deployment-capacity preflight and signing-key authorization boundaries.

## Deployment capacity — operational blocker before next redeploy

The currently running Raspberry Pi runtime remains healthy on accepted/deployed product SHA `1d226d6ddcd0c009b8f83367599d7a64521190f0`.

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
