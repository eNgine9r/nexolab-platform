# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The latest merged **product baseline** is `21cddfbb041d4b5c1dc8271c1ee4604460c50170`, the squash merge of PR #519 — **add verified LE-01MP cumulative active energy**. State-only reconciliation commits may advance `main` without changing this product baseline; the actual current `main` SHA must be verified from Git rather than self-recorded inside a state file that itself changes `main` when merged.

The accepted/deployed Raspberry Pi product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**. The cumulative-energy software from PR #519 has not been deployed to the Raspberry Pi.

The accepted Raspberry Pi `LOCAL_LAN` runtime remains healthy on that deployed baseline:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

Repository software and deployed runtime remain intentionally separate. No repository merge after `1d226d6d...` is treated as Raspberry Pi runtime-accepted until controlled deployment evidence exists.

## Issue #201 — cumulative active energy software merged; final hardware boundary pending

Issue #201 **Validate LE-01MP cumulative energy, scale and rollover** remains open as `status:needs-validation`.

PR #519 merged to product `main` as `21cddfbb041d4b5c1dc8271c1ee4604460c50170`. Final verified PR head was `48bcad8f3fbb9b71cda3a438863078013fd2d9fb`.

Implemented software outcome:

- `active_energy` is exposed as `electrical.energy.active` / `kWh`;
- cumulative energy is read atomically with read-only FC03, start register `7`, count `2`;
- R7 is decoded as the high 16-bit word and R8 as the low 16-bit word of an unsigned 32-bit counter;
- `raw32 = (R7 << 16) | R8`, scale `0.01 kWh`;
- the combined raw cumulative counter is preserved as `raw_value` and is not conflated with derived interval consumption;
- the persisted LE-01MP acquisition registry migrates known v1 profiles to read-only v2 while preserving lifecycle choices and adding the `(7, 8)` energy target;
- unknown/custom LE-01MP profile versions are not rewritten automatically;
- deterministic acquisition-scale accounting now includes nine LE metrics per meter without weakening serialization, fairness or load guardrails;
- register-map and hardware-validation evidence are versioned in the repository.

Exact-head verification on `48bcad8...` was GREEN:

- CI #3304 / run `32037544241`;
- Edge image #267 / run `32037544248`, including full Device Agent unittest discovery and the new LE-01MP tests;
- Acquisition Scale Acceptance #166 / run `32037544291` with 38/144/252 active-target inventories;
- Device Agent Fleet Acceptance #794 / run `32037544260`;
- Telemetry service #1599 / run `32037544282`;
- Authenticated Dashboard Acceptance #1881 / run `32037544232`;
- Offline Bundle #1274 / run `32037544237`, including disconnected startup and persistent-data-preserving update/rollback;
- Container Supply Chain #774, Disaster Recovery TLS Fleet #735 and MQTT TLS Fleet #744.

### Real-hardware evidence already accepted for normal operation

Controlled read-only Raspberry Pi probes on installed Units `200–203` confirmed display-correlated cumulative values:

- 200/W1: `R7=20`, `R8=63791` → `13745.11 kWh`;
- 201/W2: `R7=38`, `R8=49806` → `25401.74 kWh`;
- 202/W3: `R7=17`, `R8=15498` → `11296.10 kWh`;
- 203/W4: `R7=21`, `R8=2364` → `13786.20 kWh`.

Over approximately 9 minutes 50 seconds, Unit 201 at `2520 W` advanced `+0.28 kWh`, Unit 202 at `228 W` advanced `+0.04 kWh`, and zero-load Units 200/203 remained unchanged. The Device Agent returned healthy after the controlled probes. No Modbus write, meter reset, configuration mutation or electrical installation change occurred.

This proves normal-operation address/count/type/word-order/scale/unit/display correlation and monotonic behavior. **Full Issue #201 hardware acceptance is still pending** an explicitly approved restart/power-cycle observation and consequent rollover/reset/discontinuity classification. No such physical action is implied or authorized by the software merge.

## Autonomous Sprint selection — no independent Ready package after #201 software merge

A fresh GitHub audit after PR #519 returns **zero open Issues labelled `status:ready`**.

Issue #201 itself is `status:needs-validation`, because its remaining acceptance requires a controlled physical restart/power-cycle observation. Other existing non-Ready lanes include:

- remaining Epic #450 selector consumer integrations for Reports, Alarms and Equipment Maps — product order not repository-defined;
- #245 standalone offline Raspberry Pi monitoring — `status:needs-validation`;
- #444 LOCAL_LAN user administration — controlled runtime acceptance blocked;
- #189 backup/restore/rollback/power-loss acceptance — hardware evidence blocked.

Autonomous product implementation therefore requires either an explicit Product Owner priority for another independent Work Package or the approved physical action needed to advance a `needs-validation` lane.

## Existing operational blockers

### Issue #444

Software remains verified through PR #501. Controlled Raspberry Pi runtime acceptance remains blocked by deployment capacity and the signing-key authorization boundary.

### Issue #189

Recovery acceptance remains hardware/evidence blocked. No destructive restore, named-volume deletion, product-data deletion or hardware write is authorized.

### Raspberry Pi deployment capacity

The currently running runtime is healthy. The next controlled redeploy remains stopped by capacity preflight before runtime mutation:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

Do not bypass the guard or delete product data, PostgreSQL history, named volumes or acceptance evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
