# NEXOLAB Blockers

Updated: 2026-08-17

## Deployment capacity — no current hard blocker

The controlled Raspberry Pi deployment of exact `main` `e418ae3526319d56a9229bf1e15eb0adf47c7ef1` passed after the deployment capacity guard initially failed safely before runtime mutation.

Capacity recovery was limited to disposable caches:

- BuildKit build cache;
- npm download cache;
- Playwright-downloaded browser cache under `~/.cache/ms-playwright`.

No product data, PostgreSQL telemetry history, Docker named volume, runtime acceptance evidence, MQTT/MinIO data or hardware state was deleted. Future Raspberry Pi deployments must continue using the capacity guard because disk headroom remains bounded.

Deployment evidence: `runtime/deployments/20260817T045808Z`.

## Issue #484 — resolved

Issue #484 is closed `completed` and hardware verified on the deployed merged main.

Phase 11-R2 evidence: `runtime/evidence/issue-289-20260817T051043Z-energy-warm-return-r2`.

The previous Energy warm-return full 24h bootstrap is eliminated: cold/full history used `28` paginated requests, while each of three warm returns used one bounded approximately five-minute tail request and stayed under the `1000 ms` usable target.

## Active acceptance lane — Issue #289

Issue #289 remains open `status:in-progress` with no current hard blocker.

Completed physical/runtime acceptance includes:

- no-browser / Overview / Live Dashboard / repeated-navigation / multi-browser physical request-rate matrix;
- WebSocket reconnect and sustained outage recovery;
- Telemetry Service restart recovery;
- edge MQTT outage and SQLite outbox drain;
- disconnected `LOCAL_LAN` operation;
- REST ↔ WebSocket event identity/freshness consistency;
- route-return latency/request-count acceptance after #484.

Remaining acceptance is primarily synthetic/software scale validation using deterministic fake/recorded serial devices:

- increased active controller/channel counts;
- timeout-heavy and unavailable endpoints;
- priority deadline/fairness measurements;
- disabled-target zero normal acquisition evidence;
- scheduler defer/skip/overrun and bus-utilization evidence;
- final acceptance aggregation against Issue #289 criteria.

This work must remain read-only with respect to physical Modbus/controller state.

## Ready queue

A fresh GitHub query for open `status:ready` Issues returned none. There is no independent Ready software package to select instead of the already-active #289 lane.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

These are independent from the current #289 continuation unless they become explicit dependencies.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
