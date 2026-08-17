# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `5015e7d492d7ece67a73707ae732954c20c1dce1`, the squash merge of PR #514 — **add exact telemetry selection to Test Sessions**. State-only reconciliation commits may advance `main` without changing this product baseline; the actual current `main` SHA must be verified from Git rather than self-recorded inside a state file that itself changes `main` when merged.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. No controlled Raspberry Pi deployment was performed for Issue #513.

The current accepted Raspberry Pi `LOCAL_LAN` runtime remains healthy on that deployed baseline:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #513 — completed and merged

Issue #513 **Integrate canonical TelemetryPointSelector into Test Sessions** is closed completed / `status:done` through PR #514, product merge `5015e7d492d7ece67a73707ae732954c20c1dce1`.

Final verified PR head: `445222e4339d939b9475c4b82f3ba9396a3b484c`.

Delivered outcome:

- the Test Sessions equipment step uses the canonical hierarchical `TelemetryPointSelector`;
- the selectable hierarchy is derived from real organization-scoped local inventory intersected with the server-authoritative validated production session binding contract;
- exact node/equipment/channel/metric/unit identity prevents unsupported or drifted points from being selectable;
- at least one validated telemetry point is required before the wizard can continue;
- committed selection survives Back/Next navigation;
- session creation persists exactly the selected validated subset as individual bindings;
- no hidden fallback to all 34 production bindings exists;
- stable per-binding idempotency keys and frozen retry selection protect partial-create retries;
- the binding-options API is read-only and reuses the same server production contract already used for binding validation;
- `/sessions/new` remains production-build/prerender safe because Sessions API client construction is deferred to browser callbacks;
- no database migration, dependency change, acquisition scheduler change, new WebSocket subscription, Modbus write, controller write or hardware write was introduced.

Final exact-head verification was GREEN:

- CI #3294 / run `32034864169` — format, lint, typecheck, full test suite and production Next.js build GREEN;
- Test Sessions Browser Acceptance #882 / run `32034864360` — canonical selector-subset persistence plus the existing production session flow GREEN;
- Telemetry service #1597 / run `32034864089` — compile, migrations, PostgreSQL/MQTT/REST/WebSocket/object storage, outage recovery, offline SQL and container build GREEN;
- Offline Bundle #1269 / run `32034864363` — disconnected clean-host startup with blocked egress/pull disabled and persistent-data-preserving update/rollback GREEN;
- Authenticated Dashboard Acceptance #1876 and Disaster Recovery Browser #766 were GREEN on the same exact SHA after successful retries of transient browser-only failures;
- Security Browser, Reports Browser, Refrigeration Browser, Offline Auth, MQTT TLS, Device Agent Fleet, Broker Control, Container Supply Chain, Disaster Recovery domain/TLS and Capacity Release gates were GREEN.

Completion classification:

`software/browser/backend/offline verified; Raspberry Pi deployment/operator acceptance not performed and not required by Issue #513`

## Autonomous Sprint selection — hard blocker after #513

Fresh post-merge GitHub audit returns **zero open Issues labelled `status:ready`**.

Per NEXOLAB Autonomous Sprint policy, absence of an independent Ready Work Package is a hard selection blocker. No next product Issue is promoted or invented automatically where the repository does not define the priority.

Current non-Ready candidates are:

- Epic #450 remaining selector consumer integrations — Reports, Alarms and Equipment Maps; each must be a separate focused Issue/PR and their order requires Product Owner priority;
- #245 standalone offline Raspberry Pi monitoring — `status:needs-validation`, requires real physical Raspberry Pi acceptance actions;
- #444 LOCAL_LAN user administration — `status:blocked`, software verified but controlled runtime acceptance is blocked;
- #189 backup/restore/rollback/power-loss acceptance — `status:blocked`, requires controlled hardware/evidence work.

## Epic #450 — remaining consumers stay separate

Completed Epic #450 work includes #451, #453, #457, #461, #465, #507 and now #513.

Work Package 5 continues to require Reports, Alarms and Equipment Maps selector integrations as separate focused follow-up Issues/PRs. Their execution order is not repository-defined, so Epic #450 is not closed or advanced by assumption.

## Issue #507 — completed and merged

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** remains closed completed / `status:done` through PR #510, product merge `ba988930ba78bc44c6ec6b003a13af79d552f9fa`.

Its classification remains:

`software/browser/offline verified; Raspberry Pi operator acceptance pending`

## Issue #444 — software verified; Raspberry Pi runtime acceptance pending

PR #501 merged as `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser gates GREEN.

Issue #444 remains open `status:blocked` because its acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. Boundaries remain:

- safe redeploy is stopped by deployment-capacity preflight;
- local signing-key generation/activation/rotation remains outside current authorization and requires Product Owner action if needed for final acceptance.

## Issue #189 — hardware/evidence blocked

Issue #189 **Prove backup, restore, rollback and power-loss recovery** remains open `status:blocked`.

Complete acceptance requires controlled central-host and Raspberry Pi evidence. No destructive production restore, named-volume deletion, product-data deletion, Modbus write or hardware write is authorized.

## Raspberry Pi deployment capacity

The currently running runtime is healthy. The next controlled redeploy remains stopped by capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational constraint for the next controlled redeploy only. Do not bypass the capacity guard or delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
