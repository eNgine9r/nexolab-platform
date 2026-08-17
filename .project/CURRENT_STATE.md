# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The repository selection baseline is `db69046da24e20a642485f7d7dfd5df80f48312e`, the squash merge of PR #509 — **reconcile closed #355/#357 and promote Overview #507**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. The controlled Raspberry Pi `LOCAL_LAN` runtime remains healthy on that accepted product head:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until a controlled deployment/retest produces evidence.

## Issue #507 — software/browser/offline verified; ready for merge

Issue #507 **Make Overview telemetry graph full-width and move secondary panels below** is implemented on `feat/507-overview-full-width-chart` in PR #510.

Product verification head:

`394fe941a3c80e6f76bc6be64a1ff54f0be9f463`

Implemented product outcome:

- the canonical Overview temperature chart is the first full-width operator workspace;
- the previous `Production node` and `Telemetry alarms` side panels now render below it in a responsive one-column/two-column grid;
- the chart renderer, telemetry hooks, history contracts and WebSocket ownership are unchanged;
- the sessions, equipment-layout and camera composition remains unchanged;
- component regression covers deterministic graph-first DOM order and responsive grid classes;
- production browser acceptance checks graph width/order and secondary-panel placement at 360/1440/1920 px.

Exact product-head verification is GREEN:

- CI #3267 / run `32025536430` — format, lint, typecheck, full tests and production build GREEN;
- Refrigeration Browser Acceptance #1778 / run `32025536533` — GREEN;
- Authenticated Dashboard Acceptance #1853 / run `32025536598` — GREEN, including one WebSocket, bounded history, chart continuity, 360/1440/1920 geometry and zero acquisition mutations;
- Offline Bundle #1246 / run `32025536444` — GREEN, including disconnected startup with egress blocked and pull disabled plus update/rollback persistent-data preservation.

Completion classification before Raspberry Pi operator evidence:

`software/browser/offline verified; Raspberry Pi operator acceptance pending`

The Raspberry Pi acceptance classification does not block this focused software merge. It must not be claimed until real operator evidence exists.

## Issue #508 — completed state reconciliation

Issue #508 and PR #509 are completed. PR #509 merged as `db69046da24e20a642485f7d7dfd5df80f48312e` and removed stale future-work treatment of #355/#357 while promoting #507.

## Completed product work

- #355 **Load Live Dashboard channel inventory without telemetry-history timeout** — closed completed; any Raspberry Pi latency evidence is separate.
- #357 **Hydrate refrigeration image, layout and sensor placements immediately** — closed completed; any Raspberry Pi perceived-latency evidence is separate.
- Epic #282 / Issue #289 performance and acquisition acceptance — completed with hardware/runtime evidence already recorded.

## Issue #444 — software verified; Raspberry Pi runtime acceptance pending

PR #501 merged as `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser gates GREEN.

Issue #444 remains open `status:blocked` because its acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. The currently recorded boundaries remain:

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

## Ready queue audit

Immediately before the #507 merge checkpoint, a fresh GitHub search found **zero open Issues labelled `status:ready`** because #507 is currently `status:in-progress` and all previously selected software predecessors are completed.

Other open critical items are not automatically promoted:

- Epic #450 remains open until #507 is merged and the complete child sequence is audited;
- #245 remains `status:needs-validation` and includes real Raspberry Pi standalone acceptance steps, so it is not a Ready software Work Package;
- #444 and #189 remain blocked evidence/runtime lanes.

A fresh post-merge Ready audit is required before selecting the next Work Package.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
