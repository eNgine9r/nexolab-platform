# NEXOLAB Current State

Updated: 2026-08-18

## Repository and deployed baseline

The latest merged **product baseline** is `ef9d69b63abecee39ff7c120ed9d11ff40082a36`, the squash merge of PR #547 — **Equipment Map TelemetryPointSelector integration**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. Issue #546 and other later repository changes are not claimed as Raspberry Pi runtime acceptance until a separately controlled deployment produces physical/runtime evidence.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`. The next controlled Raspberry Pi redeploy remains blocked by the capacity preflight and must not be bypassed by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #546 — completed and merged

Issue #546 **Replace Equipment Map sensor dropdowns with TelemetryPointSelector** is closed `status:done` through PR #547 / product merge `ef9d69b63abecee39ff7c120ed9d11ff40082a36`.

Product outcome:

- Equipment Map Add and Replace flows reuse the canonical hierarchical `TelemetryPointSelector` instead of flat channel dropdowns;
- selection remains single-point and explicit: Confirm mutates the staged configuration, while Cancel produces no staged-config leakage;
- offline, stale, no-data and planned configured channels remain eligible when otherwise valid and unbound;
- already placed channels and cross-equipment binding conflicts remain fail-closed;
- the canonical organization scope is handed explicitly from `SecurityAwareRefrigerationLayoutWorkspace` through `CameraScopedLayoutEditor` to `SensorPlacementManager`;
- `SensorPlacementManager` no longer obtains a second organization authority from global security credentials;
- persistence still uses the existing atomic `replaceSensorConfiguration` path with unchanged optimistic concurrency, audit attribution, marker metadata, coordinates and layout lifecycle;
- selector interaction adds no telemetry history owner, WebSocket owner, acquisition/scheduler work or physical polling.

Final implementation head `fcf64d0fa842293facbc9762a85446f8898b43e2` was synchronized with `main` (`behind=0`) and GREEN:

- CI #3437;
- Refrigeration Browser Acceptance #1858;
- Authenticated Dashboard Acceptance #1967;
- Offline Bundle #1371;
- Security Browser Acceptance #1192;
- Acquisition Scale Acceptance #174;
- Disaster Recovery Browser #832.

The final diff contained eight authorized product/verification files and had no open review threads. No Raspberry Pi deployment or new hardware acceptance was required or claimed for #546.

## Sprint selection — next Ready product Work Package

The post-#546 repository audit identifies exactly one current open product Issue carrying `status:ready`:

**Issue #548 — Add GitHub-aware safe Raspberry Pi update orchestration.**

#548 extends the existing privileged version-management control plane. GitHub remains update-plane only; core `LOCAL_LAN` monitoring must remain functional with no internet/GitHub access. The package must preserve package/schema/capacity/backup/authorization gates and cannot introduce browser shell execution, Modbus/hardware writes, persistent-data deletion or mandatory cloud runtime dependencies.

State-only Issue #553 reconciles these facts before #548 implementation begins.

## Existing operational blockers

- #201 cumulative-energy normal operation is hardware verified; approved restart/power-cycle and rollover/reset/discontinuity evidence remains pending.
- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity/signing-key boundaries.
- #189 recovery acceptance remains hardware/evidence blocked.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- next Raspberry Pi redeploy remains capacity-blocked: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`.

These blockers do not prevent software implementation of #548, but they do block any controlled Raspberry Pi deployment/activation step that depends on the same capacity boundary.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
