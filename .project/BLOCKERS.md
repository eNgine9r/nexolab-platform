# NEXOLAB Blockers

Updated: 2026-08-17

## Autonomous Sprint selection — hard blocked after Issue #544: no Ready product Work Package

Issue #536 / PR #539 is completed and merged as product baseline `27e21a7ff6380c8961ff83e8507c008fcd05bf8d`. The post-merge repository audit finds **zero open product Issues carrying `status:ready`**.

Issue #544 is state-only reconciliation for the completed Alarms selector package and does not authorize a new product implementation lane. Epic #450 still identifies Equipment Maps as a possible later selector consumer, but no focused Equipment Maps child Issue is currently open and Ready. Open maintenance proposals and physical-validation lanes are not auto-promoted into product work.

After #544 is merged, absence of an independent Ready product task is a hard blocker under the Sprint execution policy. Product Owner selection or creation/promotion of a focused Ready Work Package is required before another product branch starts.

## Issue #536 — completed; no implementation blocker

The canonical `TelemetryPointSelector` is now integrated into `/alerts`. Server-authoritative exact telemetry scope is applied before count/order/pagination, malformed/oversized narrowed scope fails closed, and the legacy omitted-scope feed remains compatible.

Exact implementation head `a903710ee34b37181770d87640ec31f2efeda948` was GREEN in CI #3413, Alerts Browser #861, Telemetry service #1646, Authenticated Dashboard #1960 and Offline Bundle #1353, plus the relevant fleet/security/recovery gates. No Raspberry Pi deployment or new hardware acceptance was required.

## Governance record — state-only direct-main deviation

Commit `907edd86552130dde50b70579fb9945eedc3f503` changed only repository state text directly on `main` while correcting stale `CURRENT_STATE.md` wording. This bypassed the required Issue → branch → PR path.

The deviation changed no product/runtime code, hardware state, persistent data, deployment or safety boundary. It is recorded explicitly and is not an accepted precedent. Issue #544 restores the required state-only branch/PR workflow.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified: read-only FC03 R7:R8 decoding, `0.01 kWh` scale, display correlation and monotonic growth under load.

Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance. The merged period-consumption read model deliberately fails closed on negative delta rather than inventing rollover semantics.

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

None is auto-promoted while no focused product Issue is explicitly Ready.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
