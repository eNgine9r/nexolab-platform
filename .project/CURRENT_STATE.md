# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `df91a5bc0f55ef7d3be029fd743dd4fa26218afc`, the squash merge of PR #527 — **surface verified LE-01MP cumulative kWh in Energy Monitoring**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. Neither the LE-01MP cumulative-energy software from PR #519 nor the Energy UI from PR #527 has been deployed to the Raspberry Pi.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`, with central PostgreSQL/MQTT/Telemetry healthy, edge MQTT/Device Agent healthy, and one serialized RS-485 worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #526 — completed and merged

Issue #526 **Surface verified LE-01MP cumulative energy in Energy Monitoring** is closed `status:done` through PR #527 / merge `df91a5bc0f55ef7d3be029fd743dd4fa26218afc`.

Product outcome:

- `/energy` accepts `electrical.energy.active` / `kWh` for W1–W4 with two-decimal formatting;
- cumulative energy appears in the latest-values matrix and existing bounded PostgreSQL history selector;
- each meter card shows the cumulative total without presenting it as interval consumption;
- the stale `Накопичена енергія недоступна` boundary is removed;
- evidence status truthfully says normal-operation semantics are verified while #201 restart/power-cycle/rollover acceptance remains pending;
- the authenticated Energy browser flow proves local MQTT ingestion, current kWh, cumulative-history query selection, authorization, and live WebSocket update;
- no backend schema, acquisition, scheduler, dependency, cloud-runtime, Modbus-write or hardware-action change was introduced.

Final PR head `7e94ba32b2b23492bcaeb19cdb9f073b0a439f81` had GREEN:

- CI #3330 / run `32040481038`;
- Refrigeration Browser Acceptance #1804 / run `32040480994`;
- Authenticated Dashboard Acceptance #1898 / run `32040480992` after a retry of two unrelated transient Live/equipment WebSocket assertions; the complete retry was GREEN;
- Offline Bundle #1291 / run `32040481023`, including disconnected startup and persistent-data-preserving update/rollback.

No Raspberry Pi deployment/operator acceptance is claimed for PR #527.

## Issue #201 — normal-operation hardware verified; full power-cycle boundary pending

Issue #201 remains open `status:needs-validation`.

Verified normal-operation semantics remain:

- read-only FC03 start register `7`, count `2` atomically;
- R7 high word + R8 low word, unsigned uint32, scale `0.01 kWh`;
- Units `200–203` correlated with physical W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- no Modbus write, reset, configuration mutation or electrical installation change occurred.

Full #201 hardware acceptance still requires an explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification.

## Active Work Package — Reports #521

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is `status:in-progress` with draft PR #529 `feat: select exact telemetry evidence for Reports`.

PR #529 is actively advancing on `feat/521-reports-telemetry-selector`; inspect GitHub for its exact current head rather than copying a moving implementation SHA into current-state documentation. Preserve #521 as the single active implementation package; do not start another independent software Work Package while it remains active.

Reports boundaries remain unchanged: selector eligibility comes from persisted session bindings, report sources remain immutable/content-hashed, omitted selection remains backward compatible, excluded bindings must not remain in evidence artifacts, and selector interaction must create zero new acquisition/Modbus work.

## Existing operational blockers

- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity and signing-key authorization boundaries.
- #189 recovery acceptance remains hardware/evidence blocked; no destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- The next controlled Raspberry Pi redeploy remains stopped by capacity preflight: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`. Do not bypass the guard or delete product data/history/volumes/evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
