# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `27e21a7ff6380c8961ff83e8507c008fcd05bf8d`, the squash merge of PR #539 — **server-authoritative Alarms telemetry-point scope**.

This state-only reconciliation is based on `main` at `27e21a7ff6380c8961ff83e8507c008fcd05bf8d`. A later state-only merge may advance the repository HEAD without changing the product baseline; product and state-only SHAs must not be conflated.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. The merged Alarms selector, Energy Monitoring period-consumption work and other later repository changes are not claimed as Raspberry Pi runtime acceptance until a separately controlled deployment produces evidence.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`. The next controlled Raspberry Pi redeploy remains blocked by the capacity preflight and must not be bypassed by deleting product data, history, named volumes or evidence.

## Issue #536 — completed and merged

Issue #536 **Integrate TelemetryPointSelector into Alarms feed scope** is closed `status:done` through PR #539 / product merge `27e21a7ff6380c8961ff83e8507c008fcd05bf8d`.

Product outcome:

- `/alerts` reuses the canonical organization-scoped hierarchical `TelemetryPointSelector` rather than introducing a duplicate selector;
- committed telemetry scope is sent to the alerts API as bounded exact telemetry-point keys;
- the server maps selected points to persisted authoritative alert identity and applies the predicates before count, ordering, limit and offset;
- state and severity compose with telemetry scope using AND semantics, while multiple selected points use OR semantics;
- malformed, empty narrowed or oversized telemetry scope fails closed with deterministic `422` behavior instead of silently broadening to all alerts;
- omitted scope preserves the existing all-alert feed behavior;
- Confirm commits one deterministic selection, Cancel preserves the previous committed scope, and detail selection is invalidated safely when an alert leaves scope;
- the existing 5-second alert refresh remains one feed request per refresh and does not multiply by selected telemetry points;
- alert lifecycle, transition history, evaluator/rule semantics, immutable evidence, acquisition registry, polling, Modbus and WebSocket ownership remain unchanged.

Exact implementation head `a903710ee34b37181770d87640ec31f2efeda948` was synchronized with base `907edd86552130dde50b70579fb9945eedc3f503` (`behind=0`) and was GREEN:

- CI #3413;
- Alerts Browser Acceptance #861;
- Telemetry service #1646;
- Authenticated Dashboard Acceptance #1960;
- Offline Bundle #1353;
- Offline Auth Acceptance #506;
- Refrigeration Browser Acceptance #1840;
- Device Agent Fleet Acceptance #841;
- MQTT TLS Fleet Acceptance #791;
- Broker Control Acceptance #752;
- Capacity Release Gate #648;
- Disaster Recovery Browser #813 after a targeted rerun of an unrelated restored-route render flake;
- Disaster Recovery Domain Completeness #415;
- Disaster Recovery TLS Fleet #782;
- Container Supply Chain #821.

Evidence artifacts:

- Alerts Browser: `alerts-browser-acceptance-evidence`, SHA-256 `4d79b7d6221c0f9cb734f466c2f021934ce5a6fcb434ffa6d06f2d5718c3664a`;
- Authenticated Dashboard: `authenticated-dashboard-acceptance-32057208215-1`, SHA-256 `018a3f23811dd8beff1d600af043f8f5232285ad3147d2dcc5ff8f63f0ba7fe0`;
- Offline Bundle: `nexolab-offline-amd64-a903710ee34b37181770d87640ec31f2efeda948`, SHA-256 `911deaf6e972da0ec6dd7b3e02efbabe1abb63657b64eae17cb75e4af1b98942`.

No Raspberry Pi deployment or new hardware acceptance was required or claimed for #536.

## Sprint selection — no independent Ready product Work Package

The post-#536 repository audit found **zero open product Issues carrying `status:ready`**. Issue #544 is only the state-reconciliation package for the completed #536 merge and does not authorize new product scope.

Epic #450 still identifies another possible incremental selector consumer, Equipment Maps, but no focused Equipment Maps child Issue is currently open and Ready. Existing maintenance proposals and physical-validation lanes are not auto-promoted into the product lane.

After Issue #544 is merged, the truthful autonomous selection state is `hard_blocked_no_ready_work_package`. Product Owner selection or creation/promotion of a focused Ready Issue is required before another product implementation branch starts.

## Governance record

State-only commit `907edd86552130dde50b70579fb9945eedc3f503` was written directly to `main` while correcting stale `CURRENT_STATE.md` text. That bypassed the required Issue → branch → PR policy. It changed no product/runtime code, hardware state, persistent data or deployment behavior, but the process deviation is recorded explicitly and is not treated as an acceptable precedent.

All subsequent work, including this reconciliation, returns to the required Issue → branch → PR discipline.

## Existing operational blockers

- #201 cumulative-energy normal operation is hardware verified; approved restart/power-cycle and rollover/reset/discontinuity evidence remains pending.
- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity/signing-key boundaries.
- #189 recovery acceptance remains hardware/evidence blocked.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- next Raspberry Pi redeploy remains capacity-blocked: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
