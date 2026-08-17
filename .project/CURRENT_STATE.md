# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The repository software baseline is `efd190a70309039d498e2a9bab2cf47c3598e8b7`, the squash merge of PR #501 — **restore LOCAL_LAN local user administration availability**.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. The controlled Raspberry Pi `LOCAL_LAN` runtime is healthy on that accepted product head:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime are intentionally recorded separately. No later repository merge is treated as Raspberry Pi runtime-accepted until a controlled deployment/retest produces evidence.

## Issue #444 — software verified; Raspberry Pi runtime acceptance pending

PR #501 merged as `efd190a70309039d498e2a9bab2cf47c3598e8b7` after exact-head verification.

GREEN evidence includes:

- CI (formatting, lint, typecheck, tests and production build);
- Offline Auth Acceptance;
- Authenticated Dashboard Acceptance;
- Telemetry Service;
- Container Supply Chain;
- Offline Bundle disconnected runtime proof;
- Security, Nodes, Alerts, Reports, Test Sessions and fleet/browser acceptance gates.

The first Disaster Recovery Browser attempt failed on a restored refrigeration heading assertion outside the five-file #444 diff. The exact same PR head passed on an isolated rerun without code changes, so that attempt is classified as transient/flaky evidence rather than a #444 regression.

Issue #444 remains open `status:blocked` because its own acceptance plan still requires a controlled Raspberry Pi `LOCAL_LAN` retest. Software is verified; runtime acceptance is not claimed.

## Raspberry Pi deployment capacity

The currently running runtime is healthy. The next controlled redeploy remains stopped by capacity preflight **before runtime mutation**:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Classification: soft operational constraint for the next controlled redeploy only. Do not bypass the capacity guard or delete product data, PostgreSQL history, named volumes or acceptance evidence. Signing-key generation/activation/rotation is also outside current authorization; if a later acceptance step requires it, that becomes a hard blocker requiring Product Owner action.

## Performance and data acquisition optimization — completed

Epic #282 and final acceptance Issue #289 are closed `completed`.

Accepted evidence includes hardware polling invariants, deterministic scheduler scale/fairness, REST/WebSocket truthfulness, MQTT outage/outbox recovery, Energy warm-route reuse, terminal Offline recovery and disconnected `LOCAL_LAN` browser operation.

Key evidence:

- `runtime/evidence/issue-289-20260817T080201Z-phase12b-postfix-r2`
- `runtime/evidence/issue-289-20260817T082747Z-disconnected-browser-routes-r2`

## Ready queue

The single selected next Ready Work Package is:

**Issue #355 — Load Live Dashboard channel inventory without telemetry-history timeout** (`priority:critical`).

Product outcome:

- editor inventory comes from the organization-scoped canonical measurement catalog, not paginated telemetry history;
- active eligible channels remain selectable even without a latest sample;
- response is bounded and deterministic;
- optional latest metadata cannot turn inventory discovery into a telemetry-history scan;
- existing selected-series latest/history/WebSocket behavior remains unchanged;
- no acquisition registry, polling cadence, Modbus or hardware-write behavior changes;
- PostgreSQL timing/query-plan evidence and Raspberry Pi runtime latency acceptance are recorded separately.

Critical ordering after #355, subject to a fresh dependency/blocker audit at each boundary:

1. #357 — refrigeration Raspberry Pi perceived-latency closeout;
2. #189 — backup/restore/rollback/power-loss recovery acceptance;
3. #450 — chart reliability, Live Data UX and hierarchical telemetry selection Epic.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
