# NEXOLAB Blockers

Updated: 2026-08-17

## Critical active blocker — Issue #493 blocks Issue #289 Phase 12B

Issue #493 — **Live telemetry Retry does not restart terminal Offline shared WebSocket transport** — is an active critical product blocker discovered by Issue #289 truthful-state acceptance.

Controlled Raspberry Pi reproductions on deployed product SHA `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`:

- Live Data Explorer: `runtime/evidence/issue-289-20260817T060548Z-terminal-offline-ui-r4`;
- Saved Live Dashboard: `runtime/evidence/issue-289-20260817T061801Z-terminal-offline-ui-r4`.

Both prove that after reconnect exhaustion and network-path restoration:

- terminal `Offline` remains truthful with no active WebSocket;
- Chromium NetworkService remains alive;
- physical acquisition continues independently;
- Live Data **Повторити** or Saved Dashboard **Перепідключити** does not create a fresh WebSocket;
- `websocket_clients` remains `0` for 40 seconds after manual Retry;
- no F5, backend/MQTT/Device Agent restart or hardware write occurs.

Focused fix: branch `fix/493-terminal-offline-transport-restart`, PR #496. Issue #289 must not close until #493 is GREEN, merged, deployed and Phase 12B passes on the exact merged product head.

## Deployment capacity — no hard blocker

The controlled Raspberry Pi remains healthy at deployed product SHA `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`.

Previous deployment-capacity recovery was limited to disposable BuildKit, npm and Playwright browser caches. No product data, PostgreSQL telemetry history, Docker named volume, runtime acceptance evidence, MQTT/MinIO data or hardware state was deleted. Future deployments must continue using the capacity guard because disk headroom remains bounded.

## Issue #289 completed gates

Completed physical/software acceptance includes:

- no-browser / Overview / Live Dashboard / repeated-navigation / multi-browser physical request-rate matrix;
- transient WebSocket reconnect and Telemetry Service restart recovery;
- edge MQTT outage and SQLite outbox drain;
- Phase 12A UI stale-with-retained-values and automatic Live recovery;
- disconnected `LOCAL_LAN` operation;
- REST ↔ WebSocket event identity/freshness consistency;
- route-return latency/request-count acceptance after Issue #484;
- deterministic fake/recorded scale matrix with `40/40` assertions across `34 / 136 / 240` targets, disabled-target zero acquisition, timeout isolation, fairness, overrun evidence and zero Modbus writes.

The only current blocker for final #289 truthful-state completion is #493 terminal Offline manual recovery.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

These remain independent from #493/#289 unless explicitly linked.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
