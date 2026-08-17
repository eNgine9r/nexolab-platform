# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `1c17719c4dccbef735d58fdea9be87d44f8b8a46`, the squash merge of PR #529 — **select exact telemetry evidence for Reports**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. The LE-01MP cumulative-energy software from PR #519, the Energy UI from PR #527, and the Reports selector/evidence work from PR #529 have not been deployed to the Raspberry Pi.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`, with central PostgreSQL/MQTT/Telemetry healthy, edge MQTT/Device Agent healthy, and one serialized RS-485 worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #521 — completed and merged

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is closed `status:done` through PR #529 / merge `1c17719c4dccbef735d58fdea9be87d44f8b8a46`.

Product outcome:

- `/reports` uses the canonical hierarchical `TelemetryPointSelector` over the selected terminal session's persisted bindings;
- current inventory enriches taxonomy but does not determine report eligibility or silently drop persisted bindings;
- new session selection defaults to the complete persisted binding set and invalidates any prior session selection;
- explicit binding IDs are server-validated, canonicalized in persisted session-binding order and committed to immutable `source-snapshot.json` metadata;
- telemetry, limits and binding-scoped alert evidence are filtered before source hashing and artifact generation;
- session-global/unbound evidence remains deterministic;
- omitted selection preserves the legacy all-session evidence path;
- reusing an idempotency key with different selection intent fails closed;
- existing report versions remain immutable;
- selector interaction introduces no physical polling, acquisition-registry, scheduler, Modbus, WebSocket or telemetry-history mutation.

Final PR head `b1d3003d36a36ca1eef4bc88952a76e6ab5f9a15` had the complete exact-head matrix GREEN:

- CI #3362 / run `32043381179`;
- Reports Browser Acceptance #882 / run `32043381173`;
- Rendered Reports Browser Acceptance #727 / run `32043381196`;
- Telemetry service #1629 / run `32043381174` after a targeted rerun of an unrelated PostgreSQL planner nondeterminism;
- Authenticated Dashboard Acceptance #1920 / run `32043381172`;
- Offline Bundle #1313 / run `32043381181`, including egress-blocked disconnected startup with pull disabled and persistent-data-preserving update/rollback;
- Offline Auth Acceptance #490 / run `32043381175`;
- Refrigeration Browser Acceptance #1821 / run `32043381149`;
- Disaster Recovery Browser #796 / run `32043381163` after a targeted rerun of an unrelated restored-route render flake;
- Disaster Recovery Domain Completeness #398 / run `32043381151`;
- Disaster Recovery TLS Fleet #765 / run `32043381185`;
- Container Supply Chain #804 / run `32043381177`;
- Device Agent Fleet Acceptance #824 / run `32043381182`;
- MQTT TLS Fleet Acceptance #774 / run `32043381164`;
- Broker Control Acceptance #735 / run `32043381150`;
- Capacity Release Gate #631 / run `32043381195`.

No Raspberry Pi deployment or hardware acceptance is required or claimed for #521; it is a software/browser/backend/offline consumer integration.

## Issue #526 — completed and merged

Issue #526 **Surface verified LE-01MP cumulative energy in Energy Monitoring** remains closed `status:done` through PR #527 / merge `df91a5bc0f55ef7d3be029fd743dd4fa26218afc`.

`/energy` presents `electrical.energy.active` / `kWh` in latest values, bounded history and meter cards without misrepresenting cumulative totals as interval consumption. Its final head `7e94ba32b2b23492bcaeb19cdb9f073b0a439f81` was software/browser/offline verified. No Raspberry Pi deployment is claimed for PR #527.

## Issue #201 — normal-operation hardware verified; full power-cycle boundary pending

Issue #201 remains open `status:needs-validation`.

Verified normal-operation semantics remain:

- read-only FC03 start register `7`, count `2` atomically;
- R7 high word + R8 low word, unsigned uint32, scale `0.01 kWh`;
- Units `200–203` correlated with physical W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- no Modbus write, reset, configuration mutation or electrical installation change occurred.

Full #201 hardware acceptance still requires an explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification.

## Ready audit — hard blocked pending Product Owner priority

The post-#521 merge audit returns **zero open `status:ready` Issues**.

There is no active product implementation Work Package. Open pull requests are Dependabot dependency lanes only and are not repository-backed Ready product work.

Autonomous Sprint execution is therefore hard blocked as `hard_blocked_no_ready_work_package`. Remaining Epic #450 selector consumers include Alarms and Equipment Maps, but the repository does not currently establish which one is next. Do not promote, order or implement either by assumption.

## Existing operational blockers

- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity and signing-key authorization boundaries.
- #189 recovery acceptance remains hardware/evidence blocked; no destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- The next controlled Raspberry Pi redeploy remains stopped by capacity preflight: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`. Do not bypass the guard or delete product data/history/volumes/evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
