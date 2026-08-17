# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `1c17719c4dccbef735d58fdea9be87d44f8b8a46`, the squash merge of PR #529 — **select exact telemetry evidence for Reports**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`. The cumulative-energy driver/UI work from PR #519/#527 and the Reports selector from PR #529 have not been deployed to the Raspberry Pi.

The accepted `LOCAL_LAN` runtime remains healthy on deployment evidence `runtime/deployments/20260817T074249Z`, with central PostgreSQL/MQTT/Telemetry healthy, edge MQTT/Device Agent healthy, and one serialized RS-485 worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #521 — completed and merged

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is closed `status:done` through PR #529 / merge `1c17719c4dccbef735d58fdea9be87d44f8b8a46`.

Product outcome:

- Reports generation exposes the canonical hierarchical `TelemetryPointSelector` over persisted session bindings rather than arbitrary current inventory;
- current inventory may enrich taxonomy, but bindings missing from inventory remain reportable and are shown truthfully under unclassified/not-specified taxonomy;
- a newly selected terminal session defaults to all persisted reportable bindings;
- an explicit selected binding subset is validated server-side, canonicalized, recorded in the immutable report source snapshot and committed into the source hash;
- explicit selection filters binding-scoped telemetry, limits and alert-transition evidence before artifact generation while session-global evidence remains deterministic;
- omitted selection preserves the legacy unfiltered full-session evidence path;
- reusing an idempotency key with a different selection intent fails as a conflict;
- selector interaction creates no new physical polling, discovery, acquisition-registry mutation, WebSocket ownership or Modbus request.

Final implementation head `b1d3003d36a36ca1eef4bc88952a76e6ab5f9a15` had GREEN:

- CI #3362;
- Reports Browser Acceptance #882;
- Rendered Reports Browser Acceptance #727;
- Telemetry service #1629 after a targeted rerun of an unrelated PostgreSQL planner nondeterminism;
- Authenticated Dashboard Acceptance #1920;
- Offline Bundle #1313;
- Offline Auth Acceptance #490;
- Refrigeration Browser Acceptance #1821;
- Disaster Recovery Browser #796 after a targeted rerun of an unrelated route-render flake;
- Disaster Recovery Domain Completeness #398;
- Disaster Recovery TLS Fleet #765;
- Container Supply Chain #804;
- Device Agent Fleet Acceptance #824;
- MQTT TLS Fleet Acceptance #774;
- Broker Control Acceptance #735;
- Capacity Release Gate #631.

No Raspberry Pi deployment or hardware acceptance was required or claimed for #521.

## Issue #201 — normal-operation hardware verified; full power-cycle boundary pending

Issue #201 remains open `status:needs-validation`.

Verified normal-operation semantics remain:

- read-only FC03 start register `7`, count `2` atomically;
- R7 high word + R8 low word, unsigned uint32, scale `0.01 kWh`;
- Units `200–203` correlated with physical W1–W4 displays;
- loaded meters increased cumulatively while zero-load meters remained unchanged;
- no Modbus write, reset, configuration mutation or electrical installation change occurred.

Full #201 hardware acceptance still requires an explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification.

## Sprint selection — hard blocked: no Ready Work Package

The post-#521 repository audit found **zero open Issues carrying `status:ready`**. There is no active implementation Work Package and no repository-authorized next product package.

Epic #450 still names future incremental selector consumers such as Alarms and Equipment Maps, but no focused child Issue is currently open and Ready for either consumer. Existing open Dependabot PRs are maintenance proposals, not repository-selected Ready Work Packages, and must not be auto-promoted into the product lane.

Per autonomous Sprint policy, `hard_blocked_no_ready_work_package` is now the truthful selection state. Product Owner selection or creation/promotion of a focused Ready Issue is required before another implementation branch starts.

## Existing operational blockers

- #444 LOCAL_LAN user-administration runtime acceptance remains blocked by controlled redeploy capacity and signing-key authorization boundaries.
- #189 recovery acceptance remains hardware/evidence blocked; no destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.
- #245 standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires physical evidence.
- The next controlled Raspberry Pi redeploy remains stopped by capacity preflight: `free_bytes=15310114816`, `required_bytes=16595036807`, `reserve_bytes=2147483648`. Do not bypass the guard or delete product data/history/volumes/evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
