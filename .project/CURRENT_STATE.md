# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The repository selection baseline for this state reconciliation is `1a7d929351c52421e8d94cdee5469e1f017beb38`, the merge of PR #506 — **reconcile Issue #444 software merge state**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. The controlled Raspberry Pi `LOCAL_LAN` runtime is healthy on that accepted product head:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime remain intentionally separate. No later repository merge is treated as Raspberry Pi runtime-accepted until a controlled deployment/retest produces evidence.

## Completed product work discovered by fresh GitHub audit

### Issue #355 — completed

Issue #355 **Load Live Dashboard channel inventory without telemetry-history timeout** is closed `completed` / `status:done`.

Its canonical inventory implementation is already merged and software-verified: the editor inventory is backed by the bounded organization-scoped measurement catalog rather than paginated telemetry history, active eligible channels without latest samples remain selectable, and selected-dashboard latest/history/WebSocket behavior remains bounded.

Raspberry Pi latency/query-plan evidence remains a separate acceptance classification and is not inferred from CI.

### Issue #357 — completed

Issue #357 **Hydrate refrigeration image, layout and sensor placements immediately** is closed `completed` / `status:done`.

It is no longer a future software Work Package. Any remaining controlled Raspberry Pi perceived-latency evidence is an evidence lane only and must not reopen already completed software scope without a newly reproduced defect.

## Issue #444 — software verified; Raspberry Pi runtime acceptance pending

PR #501 merged as `efd190a70309039d498e2a9bab2cf47c3598e8b7` with exact-head software/offline/browser gates GREEN.

Issue #444 remains open `status:blocked` because its own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. Software is verified; runtime acceptance is not claimed.

The currently recorded boundaries remain:

- safe redeploy is stopped by deployment-capacity preflight;
- local signing-key generation/activation/rotation remains outside current authorization and requires Product Owner action if needed for final acceptance.

## Issue #189 — hardware/evidence blocked

Issue #189 **Prove backup, restore, rollback and power-loss recovery** remains open `status:blocked`.

Complete acceptance requires controlled central-host and Raspberry Pi evidence. No destructive production restore, named-volume deletion, product-data deletion, Modbus write or hardware write is authorized. Software-only preparation may proceed separately when promoted, but no physical acceptance is claimed.

## Raspberry Pi deployment capacity

The currently running runtime is healthy. The next controlled redeploy remains stopped by capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational constraint for the next controlled redeploy only. Do not bypass the capacity guard or delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Performance and data acquisition optimization — completed

Epic #282 and final acceptance Issue #289 are closed `completed`.

Accepted evidence includes hardware polling invariants, deterministic scheduler scale/fairness, REST/WebSocket truthfulness, MQTT outage/outbox recovery, Energy warm-route reuse, terminal Offline recovery and disconnected `LOCAL_LAN` browser operation.

Key evidence:

- `runtime/evidence/issue-289-20260817T080201Z-phase12b-postfix-r2`
- `runtime/evidence/issue-289-20260817T082747Z-disconnected-browser-routes-r2`

## Epic #450 continuation

Fresh GitHub audit confirms the ordered Epic #450 software sequence through #451, #453, #457, #461 and #465 is completed.

The next independent software Work Package is:

**Issue #507 — Make Overview telemetry graph full-width and move secondary panels below** (`priority:critical`).

Product outcome:

- Overview primary telemetry graph uses the full available main-content width;
- former left/right secondary panels move below into a responsive grid;
- 1440/1920 operator layouts prioritize the graph;
- 360/1440/1920 remain free of document-level horizontal overflow;
- canonical chart continuity, mixed-unit axes, Exact Inspector, one-WebSocket ownership and bounded history behavior remain unchanged;
- layout/navigation actions produce zero acquisition/discovery/configuration mutations and no Modbus/hardware writes.

Issue #507 is the single selected software `status:ready` Work Package after this reconciliation. Issue #189 and #444 remain blocked evidence/runtime lanes and do not block #507 implementation.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
