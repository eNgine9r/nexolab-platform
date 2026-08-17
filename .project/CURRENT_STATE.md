# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `21cddfbb041d4b5c1dc8271c1ee4604460c50170`, the squash merge of PR #519 — **add verified LE-01MP cumulative active energy**. State-only or repository-repair commits may advance `main` without changing this product baseline; the actual current `main` SHA must be verified from Git rather than self-recorded inside a state file that itself changes `main` when merged.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. The cumulative-energy software from PR #519 has not been deployed to the Raspberry Pi.

The accepted Raspberry Pi `LOCAL_LAN` runtime remains healthy on that deployed baseline:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #201 — software merged; physical restart/rollover validation remains separate

Issue #201 **Validate LE-01MP cumulative energy, scale and rollover** remains open as `status:needs-validation` after PR #519 merged product commit `21cddfbb041d4b5c1dc8271c1ee4604460c50170`.

Final verified PR head: `48bcad8f3fbb9b71cda3a438863078013fd2d9fb`.

Software and normal-operation hardware evidence are verified:

- cumulative `electrical.energy.active` / `kWh` is read with read-only FC03 start `7`, count `2` atomically;
- R7 high word + R8 low word decode to unsigned uint32 with scale `0.01 kWh`;
- raw cumulative value is preserved separately from any derived interval consumption;
- known persisted LE-01MP profiles migrate to read-only v2 while preserving lifecycle choices;
- deterministic acquisition-scale accounting now includes nine LE metrics per meter;
- installed Units `200–203` produced display-correlated values and truthful monotonic behavior under live load;
- no Modbus write, counter reset, configuration mutation or electrical installation change occurred.

Exact-head GREEN evidence includes CI #3304, Edge image #267, Acquisition Scale #166 with 38/144/252 targets, Device Agent Fleet #794, Telemetry service #1599, Authenticated Dashboard #1881, Offline Bundle #1274, Container Supply Chain #774, Disaster Recovery TLS #735 and MQTT TLS #744.

Full Issue #201 hardware acceptance still requires an explicitly approved restart/power-cycle observation and rollover/reset/discontinuity classification. This lane is independent from the next software Work Package and does not block Reports.

## Epic #450 — Reports selected as next Work Package

The Product Owner explicitly selected **Reports** as the next Epic #450 Work Package 5 consumer integration.

Issue #521 **Integrate TelemetryPointSelector into report evidence selection** is open, assigned, `priority:critical` and `status:ready`.

Repository-backed product outcome for #521:

- report generation from a terminal Test Session exposes the canonical hierarchical `TelemetryPointSelector`;
- selectable points are constrained by the persisted session binding set, not arbitrary global inventory;
- existing organization-scoped local inventory may enrich laboratory/zone/equipment taxonomy, but missing taxonomy is shown truthfully and bindings missing from current live inventory are not silently discarded;
- a new session selection defaults to all reportable session bindings, preserving current report evidence scope until the operator intentionally narrows it;
- an explicit selected binding subset becomes part of the immutable report source contract and source hash;
- generated `telemetry.csv` contains exactly telemetry attributed to selected bindings;
- server-side session/organization validation remains authoritative;
- omitted selection remains backward compatible with existing all-session-binding generation;
- existing immutable report versions are never rewritten;
- selector interaction creates no new physical polling, discovery, WebSocket ownership, Modbus request or acquisition scheduling behavior.

The previous `hard_blocked_no_ready_work_package` selection blocker is therefore resolved. Issue #521 is the single next Ready implementation package; Alarms and Equipment Maps remain separate future Issues/PRs and are not bundled into Reports.

## Repository repair #524 — completed

An accidental empty root `.tmp` file was created directly on `main` during connector preparation. The incident was recorded transparently as Issue #524 and repaired through normal PR #525 with a one-file diff, exact-head standard CI GREEN and no force push/history rewrite. No product/runtime/state/data/hardware behavior was changed by that empty file or its removal.

## Existing operational blockers

### Issue #444

Software remains verified through PR #501. Controlled Raspberry Pi `LOCAL_LAN` runtime acceptance remains blocked by deployment capacity and the signing-key authorization boundary.

### Issue #189

Recovery acceptance remains hardware/evidence blocked. No destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.

### Issue #245

Standalone offline Raspberry Pi monitoring remains `status:needs-validation` and requires real physical acceptance actions; it is not auto-promoted while Reports is the selected software WP.

### Raspberry Pi deployment capacity

The currently running runtime is healthy. The next controlled redeploy remains stopped by capacity preflight before runtime mutation:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Do not bypass the guard or delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
