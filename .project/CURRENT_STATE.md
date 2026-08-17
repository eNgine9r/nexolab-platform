# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The current product repository baseline is `ba988930ba78bc44c6ec6b003a13af79d552f9fa`, the squash merge of PR #510 — **make Overview chart full-width**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. No controlled Raspberry Pi deployment was performed for PR #510.

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

## Issue #507 — completed and merged

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** is closed completed / `status:done`.

PR #510 squash-merged to `main` as:

`ba988930ba78bc44c6ec6b003a13af79d552f9fa`

Implemented outcome:

- the canonical Overview temperature chart is the first full-width operator workspace;
- `Production node` and `Telemetry alarms` render below it in a responsive one-column/two-column grid;
- sessions, equipment layouts and cameras remain unchanged;
- the chart renderer, telemetry hooks, history contract and WebSocket ownership remain unchanged;
- graph-first DOM order and responsive structure have component regression coverage;
- production browser acceptance verifies graph width/order and secondary-panel placement at 360/1440/1920 px.

Final exact PR head `74bdb039744d4da427adb5aacc557e148dfc2022` was GREEN:

- CI #3271 / run `32026588140` — format, lint, typecheck, full tests and production build GREEN;
- Refrigeration Browser Acceptance #1782 / run `32026588024` — GREEN;
- Authenticated Dashboard Acceptance #1857 / run `32026588105` — GREEN, including one WebSocket, bounded history, chart continuity, zero acquisition mutations and 360/1440/1920 geometry;
- Offline Bundle #1250 / run `32026588165` — GREEN, including disconnected startup with egress blocked and pull disabled plus persistent-data-preserving update/rollback.

Completion classification remains:

`software/browser/offline verified; Raspberry Pi operator acceptance pending`

No Raspberry Pi operator/browser acceptance is claimed without real evidence.

## Epic #450 — product sequence needs a new explicit Ready decision

Fresh repository audit confirms these Epic #450 children are closed completed:

- #451 canonical chart continuity / inspector / event provenance;
- #453 equipment-centric multi-metric charts with dynamic Y axes;
- #457 graph-first Live Data composition;
- #461 reusable hierarchical `TelemetryPointSelector`;
- #465 first consumer integration into Live Dashboard editor;
- #507 Overview graph-first full-width composition.

Epic #450 Work Package 5 explicitly states that **session, report, alarm and equipment-map selector integrations are separate follow-up Issues/PRs**. Those follow-up Issues are not currently present as `status:ready` tasks and their execution order is not repository-defined. Therefore Epic #450 is not closed by assumption.

## Autonomous Sprint selection blocker

A fresh post-merge GitHub search returns **zero open Issues labelled `status:ready`**.

Per NEXOLAB Autonomous Sprint policy, absence of an independent Ready Work Package is a hard selection blocker. No new product Issue is promoted or invented automatically where the repository does not define the next priority.

Current non-Ready candidates are:

- Epic #450 remaining selector consumer integrations — product sequencing decision required before creating the next focused Issue;
- #245 standalone offline Raspberry Pi monitoring — `status:needs-validation`, requires real physical Raspberry Pi acceptance actions;
- #444 LOCAL_LAN user administration — `status:blocked`, software verified but controlled runtime acceptance is blocked;
- #189 backup/restore/rollback/power-loss acceptance — `status:blocked`, requires controlled hardware/evidence work.

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
