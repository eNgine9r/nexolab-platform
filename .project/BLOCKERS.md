# NEXOLAB Blockers

Updated: 2026-08-17

## Active implementation lane — Reports #521

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is `status:in-progress` with draft PR #529. It is the single active implementation Work Package. Issue #526 / PR #527 is completed and must not create a second active software lane.

Reports currently has no recorded hard blocker. Its existing boundaries remain authoritative: selector eligibility comes from persisted session bindings, immutable report sources remain content-hashed, omitted selection stays backward compatible, excluded bindings must not remain in generated evidence, and selector interaction creates zero acquisition/Modbus work.

## Issue #201 — Energy software/UI available; final hardware boundary pending

PR #519 merged the evidence-backed cumulative-energy read path, and PR #527 merged its Energy Monitoring operator presentation. Normal-operation hardware semantics on Units `200–203` remain verified: display correlation, read-only FC03 R7:R8 decoding at `0.01 kWh`, and truthful monotonic growth under load.

Issue #201 remains `status:needs-validation`. Full hardware acceptance still requires an explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification. No such physical action is authorized by PR #519 or #527.

The new #519/#527 product software has not been deployed to the accepted Raspberry Pi runtime.

## Issue #444 — controlled Raspberry Pi runtime acceptance blocked

Issue #444 software remains verified. Final `LOCAL_LAN` runtime acceptance is blocked by the existing deployment-capacity preflight and signing-key authorization boundary. Do not claim physical acceptance without a controlled deployment/retest.

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
- #507 Raspberry Pi operator/browser acceptance;
- #444 LOCAL_LAN user-administration runtime retest;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- Raspberry Pi version-management acceptance.

These do not replace or bundle into active Reports #521.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
