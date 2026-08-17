# NEXOLAB Blockers

Updated: 2026-08-17

## Sprint selection

Issue #537 / PR #538 is merged at `b00c996a1990dde4f5427e0caa44cc34f1e4f6a6`.

The repository audit finds zero open `status:ready` Issues. This is **not** a no-work hard blocker because Issue #536 is already `status:in-progress` with draft PR #539 on `feat/536-alarms-telemetry-selector`. This reconciliation records that existing lane without modifying or reprioritizing it.

## Issue #201 — final hardware boundary pending

Normal-operation LE-01MP semantics on Units `200–203` remain hardware verified: read-only FC03 R7:R8 uint32 at `0.01 kWh`, display correlation, and monotonic growth under load. PR #538 derives selectable-period `СПОЖИВАННЯ` from this immutable cumulative source.

Issue #201 remains `status:needs-validation`. Full hardware acceptance still requires explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification. PR #538 fails closed on a decreasing counter and does not invent rollover behavior.

## Issue #444 — controlled Raspberry Pi runtime acceptance blocked

Issue #444 software remains verified. Final `LOCAL_LAN` runtime acceptance is blocked by the existing deployment-capacity preflight and signing-key authorization boundary.

## Deployment capacity — operational blocker before next redeploy

The accepted/deployed Raspberry Pi product SHA remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. The next controlled redeploy remains stopped before mutation:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Do not bypass the guard. Do not delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Issue #189 and other physical/evidence lanes

Issue #189 remains blocked pending controlled recovery evidence. Other pending physical/evidence lanes include #201 power-cycle/rollover, #245 standalone Pi acceptance, #507 Pi operator/browser acceptance, #444 LOCAL_LAN retest, KK2/Unit 115 field retest and Raspberry Pi version-management acceptance.

None is auto-promoted while #536 is the active implementation lane.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
