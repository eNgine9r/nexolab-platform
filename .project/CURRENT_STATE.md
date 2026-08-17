# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The current `main` control-state commit is `6f0c4f3bc39c2bccbe24dafa5218a8f49cf553e3`, the state-only reconciliation after PR #510. The latest merged product baseline remains `ba988930ba78bc44c6ec6b003a13af79d552f9fa`, the squash merge of PR #510 — **make Overview chart full-width**.

Issue #513 / PR #514 is not merged yet. Its exact verified product head is `b884bf2e531e1eb6f3dbd99fbeef0ec9de77f21a`.

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

## Issue #513 — software/browser/offline verified; ready for final merge audit

Issue #513 **Integrate canonical TelemetryPointSelector into Test Sessions** is the Product Owner-selected Epic #450 Sessions Work Package. PR #514 is open from `feat/513-sessions-telemetry-selector`.

Implemented outcome on exact product head `b884bf2e531e1eb6f3dbd99fbeef0ec9de77f21a`:

- the Test Sessions equipment step uses the canonical hierarchical `TelemetryPointSelector`;
- the selectable hierarchy is derived from real organization-scoped local inventory intersected with the server-authoritative validated production session binding contract;
- identity matching includes node, equipment, channel, metric and unit, so unsupported or drifted inventory entries are not selectable;
- at least one validated telemetry point is required before the wizard can continue;
- committed selection survives Back/Next navigation;
- session creation persists exactly the selected validated subset as individual bindings;
- there is no hidden fallback to all 34 production bindings;
- stable per-binding idempotency keys and frozen retry selection protect partial-create retries from duplication or silent selection changes;
- the new binding-options API is read-only and reuses the same server production contract already used for binding validation;
- no database migration, acquisition scheduler change, WebSocket polling change, Modbus write, controller write or hardware write was introduced.

Exact-head verification is GREEN:

- CI #3290 / run `32033655886` — standalone runtime contracts, ADR/dependency policy, format, lint, typecheck, 100 test files / 442 tests and production Next.js build GREEN; `/sessions/new` prerenders successfully;
- Test Sessions Browser Acceptance #878 / run `32033655829` — GREEN; both the canonical selector-subset scenario and existing organization-scoped production session scenario pass against the controlled acceptance backend/PostgreSQL;
- Telemetry service #1593 / run `32033655867` — GREEN; compile, migrations, PostgreSQL/MQTT/REST/WebSocket/object-storage coverage, outage recovery, offline migration SQL and container build pass;
- Offline Bundle #1265 / run `32033655901` — GREEN; disconnected startup with egress blocked and pull disabled succeeds, and update/rollback preserve persistent data.

Additional exact-head browser/security/runtime workflows are GREEN, including Authenticated Dashboard, Security Browser, Reports Browser, Refrigeration Browser, Offline Auth, MQTT TLS, Device Agent Fleet, Disaster Recovery and Capacity Release gates.

Completion classification before merge:

`software/browser/backend/offline verified; Raspberry Pi deployment/operator acceptance not performed and not required by Issue #513`

## Epic #450 — Sessions selected; remaining consumers stay separate

The previous no-Ready selection blocker was resolved for the current Work Package by the Product Owner decision to continue Epic #450 with Sessions. Issue #513 was created as that focused vertical slice and is now verified for merge.

Fresh repository audit still returns zero open Issues labelled `status:ready` besides the already-active #513 lane, which is `status:in-progress` rather than Ready.

Epic #450 Work Package 5 continues to require separate follow-up Issues/PRs for remaining selector consumers. Reports, alarms and equipment maps are not automatically promoted or bundled into PR #514. Their execution order remains a post-merge Product Owner priority decision unless the repository gains a Ready task.

## Issue #507 — completed and merged

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** remains closed completed / `status:done` through PR #510, product merge `ba988930ba78bc44c6ec6b003a13af79d552f9fa`.

Its final classification remains:

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
