# NEXOLAB Current State

Updated: 2026-08-17

## Canonical deployed baseline

The controlled Raspberry Pi `LOCAL_LAN` host and GitHub `main` are aligned at exact commit `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`, the squash merge of PR #485 for Issue #484.

Controlled deployment evidence:

- `runtime/deployments/20260817T045808Z`;
- `runtime_mode=lan`;
- bind address `172.18.48.34`;
- dashboard `http://172.18.48.34:3000`;
- API `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry and edge MQTT/Device Agent ready after deployment;
- Device Agent queue depth `0`, scheduler healthy, one active `rs485-main` worker.

The deployment-capacity guard initially failed safely before runtime mutation. Capacity was recovered only through bounded disposable cache cleanup (BuildKit, npm download cache and Playwright-downloaded browser cache). No product data, named volumes, PostgreSQL telemetry history, runtime acceptance evidence or hardware state was deleted.

## Issue #484 — completed, software and Raspberry Pi hardware acceptance verified

Issue #484 — **Reuse Energy history on warm route return instead of replaying full 24h pagination** — is closed `completed`.

Software merge:

- PR #485;
- final verified source head `4f244da779c81c81e1e3d43a8c66549fe4cee300`;
- merge/current product SHA `e418ae3526319d56a9229bf1e15eb0adf47c7ef1`;
- CI `31973454509` — PASS;
- Authenticated Dashboard `31973454596` — PASS;
- Offline Bundle `31973454511` — PASS.

Physical Phase 11-R2 evidence:

- `runtime/evidence/issue-289-20260817T051043Z-energy-warm-return-r2`;
- cold/full Energy bootstrap: `28` snapshot-paginated 24h history requests;
- warm return #1: one bounded `311.716 s` tail request, usable in `627 ms`;
- warm return #2: one bounded `302.138 s` tail request, usable in `557 ms`;
- warm return #3: one bounded `302.158 s` tail request, usable in `443 ms`;
- no visible Energy loading transition on any warm return;
- telemetry latest bootstrap remained `1 -> 1`;
- one document load and one application-shell WebSocket (`maxConcurrent=1`);
- no navigation-driven acquisition mutation;
- physical requests continued `+131`, communication failures `+0`, workers healthy, one active bus worker, degraded/cooldown `0/0`.

Classification: **software verified; Raspberry Pi hardware verified**.

## Active Work Package — Issue #289

Issue #289 — **Prove acquisition scale, stability and truthful live-state behavior** — remains the active `status:in-progress` acceptance lane.

Completed #289 evidence now includes:

- five-phase real-hardware browser/request-rate matrix: no browser, Overview, Live Dashboard, repeated navigation and multiple concurrent browser pages, with no browser-driven physical Modbus amplification;
- WebSocket reconnect and sustained-outage recovery evidence;
- Telemetry Service restart recovery without duplicate committed telemetry;
- edge MQTT outage, SQLite outbox growth and deterministic drain without duplicate committed telemetry;
- disconnected `LOCAL_LAN` runtime with public egress blocked while local monitoring remained functional;
- REST ↔ WebSocket event identity/freshness consistency;
- route-return latency/request-count acceptance, including the #484 Energy warm-history correction.

The next unresolved acceptance gate is the deterministic increased-load plus timeout-heavy/unavailable-endpoint scheduler matrix using fake/recorded serial devices. It must measure priority deadlines/fairness, timeout isolation, disabled-target zero-acquisition behavior and scheduler/bus-load metrics without modifying physical controller state.

## Ready audit

A fresh GitHub query for open `status:ready` Issues returned **none**. Do not invent an independent software Work Package. Continue Issue #289 after this state-only reconciliation.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus write, hardware/controller write, production/site cutover, product persistent-data deletion, named-volume deletion or mandatory cloud runtime dependency is authorized.
