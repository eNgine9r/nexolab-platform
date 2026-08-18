# NEXOLAB Current State

Updated: 2026-08-18

## Repository and deployed baseline

The latest merged **repository product baseline** is `9c8f205fb17452205c5905eaea49ce878834a9c4`, the merge of PR #552 — **auth-aware central deployment smoke**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. Later repository changes, including #546 and #551, are not claimed as Raspberry Pi runtime acceptance until a separately approved controlled deployment produces physical/runtime evidence.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`. The failed pre-fix deployment evidence for #551 is `runtime/deployments/20260818T060358Z`.

The next controlled Raspberry Pi redeploy remains subject to the existing capacity/signing/backup safeguards and must not be bypassed by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #551 — software merged; Raspberry Pi validation pending

Issue #551 **Make central smoke gate compatible with fail-closed LOCAL_LAN authentication** is software/CI/offline verified through PR #552 / merge `9c8f205fb17452205c5905eaea49ce878834a9c4` and remains open as `status:needs-validation` until an explicitly approved Raspberry Pi LOCAL_LAN retest completes.

Product/runtime contract now verified in software:

- public `/health/ready` and `/metrics` smoke remains unchanged;
- `AUTH_MODE=disabled` preserves positive anonymous telemetry latest/history/WebSocket smoke;
- authenticated modes no longer treat expected fail-closed telemetry authentication as deployment failure;
- authenticated telemetry REST smoke explicitly requires HTTP 401 for unauthenticated requests;
- authenticated telemetry WebSocket smoke explicitly requires structured `missing_bearer_token` rejection for an empty bearer token;
- `central-smoke.sh` receives no operator password, access token, private key or auth bypass;
- the deployment route-contract check for local login and local user administration remains separate and authoritative.

Final software head `b08536a8e5a11ab10b59bb387fff54d611673f42` was synchronized with `main` (`behind=0`) and GREEN:

- CI #3445;
- Telemetry service #1652, including executable auth-mode regression, full PostgreSQL/MQTT/REST/WebSocket/object-storage tests, outage recovery, migration validation and container build;
- Offline Bundle #1376, including disconnected build/load/start with container egress blocked and pull disabled, plus update/rollback persistent-data preservation.

The final diff contained exactly three authorized files and had no open review threads or submitted reviews.

Hardware/runtime evidence remains **unverified post-fix**. A controlled Raspberry Pi retest must record exact deployed SHA, auth mode, local-auth overlay, Dashboard/API/Device Agent readiness and advancing telemetry before #551 can close.

## Issue #546 — completed and merged

Issue #546 **Replace Equipment Map sensor dropdowns with TelemetryPointSelector** is closed `status:done` through PR #547 / merge `ef9d69b63abecee39ff7c120ed9d11ff40082a36`.

Equipment Map Add/Replace uses the canonical hierarchical `TelemetryPointSelector`, explicit Confirm/Cancel, workspace-owned organization scope and the unchanged atomic `replaceSensorConfiguration` persistence path. No new telemetry ownership, acquisition work, Modbus write or hardware mutation was introduced.

## Sprint selection — next Ready product Work Package

The post-#551 merge audit identifies exactly one current open product Issue carrying `status:ready`:

**Issue #548 — Add GitHub-aware safe Raspberry Pi update orchestration.**

#548 extends the existing privileged version-management control plane. GitHub remains update-plane only; core `LOCAL_LAN` monitoring must remain functional with no internet/GitHub access. The package must preserve package/schema/capacity/backup/authorization gates and cannot introduce browser shell execution, Modbus/hardware writes, persistent-data deletion or mandatory cloud runtime dependencies.

State-only Issue #555 reconciles #551 before #548 implementation begins.

## Existing operational blockers / validation lanes

- #551 post-fix Raspberry Pi LOCAL_LAN deployment retest remains pending explicit deployment approval.
- #201 cumulative-energy normal operation is hardware verified; approved restart/power-cycle and rollover/reset/discontinuity evidence remains pending.
- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity/signing-key boundaries and now depends on a future #551 retest proving the corrected smoke path.
- #189 recovery acceptance remains hardware/evidence blocked.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- next Raspberry Pi redeploy remains capacity-gated by the last recorded preflight: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`.

These lanes do not prevent software implementation of #548, but they do prevent claiming production Raspberry Pi activation/acceptance without new evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
