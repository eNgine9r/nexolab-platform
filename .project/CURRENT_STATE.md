# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baselines

GitHub `main` is `297fc2fa28ef43d7be71d2436151a34f3e414a26`, the state-only reconciliation merge after Issue #484 hardware acceptance.

The controlled Raspberry Pi `LOCAL_LAN` product/runtime remains deployed at `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`, the product merge of PR #485. The later state-only repository commit does not require runtime redeployment.

Controlled product deployment evidence:

- `runtime/deployments/20260817T045808Z`;
- `runtime_mode=lan`;
- bind address `172.18.48.34`;
- dashboard `http://172.18.48.34:3000`;
- API `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry and edge MQTT/Device Agent ready;
- Device Agent queue depth `0`, scheduler healthy, one active `rs485-main` worker.

Deployment capacity remains bounded. Previous recovery removed only disposable BuildKit, npm and Playwright browser caches; product data, named volumes, PostgreSQL history and runtime evidence were preserved.

## Issue #484 — completed

Issue #484 — **Reuse Energy history on warm route return instead of replaying full 24h pagination** — is closed `completed` and Raspberry Pi verified.

Phase 11-R2 evidence: `runtime/evidence/issue-289-20260817T051043Z-energy-warm-return-r2`.

- cold Energy bootstrap: `28` paginated 24h history requests;
- three warm returns: exactly one bounded approximately five-minute tail request each;
- warm usable latency: `627 / 557 / 443 ms`;
- no warm loading transition;
- one application-shell WebSocket;
- physical acquisition continued `+131`, communication failures `+0`;
- no navigation-driven acquisition mutation or hardware write.

## Active acceptance lane — Issue #289

Issue #289 — **Prove acquisition scale, stability and truthful live-state behavior** — remains open `status:in-progress`.

Completed evidence includes:

- no-browser / Overview / Live Dashboard / repeated-navigation / multi-browser physical request-rate matrix with no browser-driven Modbus amplification;
- WebSocket transient reconnect and Telemetry Service restart recovery;
- edge MQTT outage, SQLite outbox growth/drain and UI stale-to-Live truthfulness;
- disconnected `LOCAL_LAN` runtime;
- REST ↔ WebSocket event identity/freshness consistency;
- route-return latency/request-count acceptance after #484;
- deterministic fake/recorded acquisition scale matrix: `40/40` assertions, `34 / 136 / 240` targets, one serialized reader, disabled targets zero executions, timeout/cooldown isolation, fairness and overrun behavior, `serial_port_opened=false`, `modbus_write_attempts=0`;
- Phase 12A operator UI observation: `Live → Застарілі дані` with retained values and no false Live label, then automatic `Live` recovery after MQTT restoration without F5/Retry.

## Critical blocker — Issue #493

Issue #493 — **Live telemetry Retry does not restart terminal Offline shared WebSocket transport** — is the active critical bug interrupting #289 Phase 12B.

Controlled Raspberry Pi reproductions on deployed product SHA `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`:

- Live Data Explorer: `runtime/evidence/issue-289-20260817T060548Z-terminal-offline-ui-r4`;
- Saved Live Dashboard: `runtime/evidence/issue-289-20260817T061801Z-terminal-offline-ui-r4`.

Both reproductions proved:

- baseline `websocket_clients=1`;
- Chromium NetworkService remained alive and unchanged;
- physical acquisition continued throughout the local API-path outage;
- after reconnect-budget exhaustion and network restoration, `websocket_clients=0` remained terminal;
- Live Data **Повторити** and Saved Dashboard **Перепідключити** failed to create a fresh WebSocket for 40 seconds;
- no F5, backend/MQTT/Device Agent restart, Modbus write or hardware mutation occurred.

Focused implementation is in branch `fix/493-terminal-offline-transport-restart`, draft PR #496. The shared route-persistent client now releases a terminal source transport when its final route/request consumer closes so the explicit Retry lifecycle can create exactly one fresh transport while retaining bounded cached samples.

Software verification remains in progress. Issue #493 and #289 Phase 12B must not be classified complete until PR #496 is GREEN, merged, deployed to the Raspberry Pi and terminal Offline → manual Retry → Live passes on the exact merged product head.

## Next action

Complete Issue #493 through focused unit/browser regression, full CI, Authenticated Dashboard Acceptance, Acquisition Scale Acceptance and Offline Bundle; merge only GREEN/current; deploy the exact merged product head using the capacity guard; rerun Phase 12B once on the controlled Raspberry Pi; then aggregate and close Issue #289 only if every remaining acceptance criterion passes.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus write, hardware/controller write, production/site cutover, product persistent-data deletion, named-volume deletion or mandatory cloud runtime dependency is authorized.
