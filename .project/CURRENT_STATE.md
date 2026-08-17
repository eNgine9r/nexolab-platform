# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The accepted product/runtime baseline is `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**.

The controlled Raspberry Pi `LOCAL_LAN` runtime is running this exact product head:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker;
- no product/runtime redeploy is required for this state-only reconciliation.

Issue #497 is a metadata-only reconciliation branch based on the accepted product head. Its merge may advance the repository SHA without changing the deployed product/runtime SHA.

## Performance and data acquisition optimization — completed

Epic #282 and final acceptance Issue #289 are closed `completed`.

Accepted evidence covers:

- normal browser/page activity does not amplify physical Modbus polling;
- no-browser, Overview, Live Dashboard, fast navigation and multi-browser hardware matrices;
- disabled targets execute zero normal acquisition work;
- one unavailable endpoint does not take unrelated channels offline;
- deterministic scheduler scale/fairness matrix: `40/40` assertions across `34 / 136 / 240` targets;
- one serialized reader, bounded fairness, timeout/cooldown isolation and overrun/deadline evidence;
- REST latest ↔ WebSocket identity/freshness consistency;
- transient WebSocket reconnect and Telemetry Service restart recovery;
- MQTT outage, durable edge outbox drain, no duplicate committed telemetry and stale-to-Live UI truthfulness;
- Energy warm-route return after Issue #484: cold `28` history requests, warm `1 / 1 / 1` bounded tail requests, `627 / 557 / 443 ms` usable latency;
- terminal Offline truthfulness and explicit manual recovery after Issue #493;
- Offline Bundle and disconnected `LOCAL_LAN` runtime/browser operation;
- zero Modbus/hardware writes during acceptance.

Final disconnected browser-route evidence:

`runtime/evidence/issue-289-20260817T082747Z-disconnected-browser-routes-r2`

Operator route sequence while public IPv4 egress was blocked:

`Overview → Refrigeration → Energy → Saved Live Dashboard → Overview`

All routes remained usable without F5, remote-asset failure or endless loading. Central/edge runtime stayed healthy and physical requests advanced `2152 → 3062`.

## Issue #493 — completed and hardware verified

PR #496 merged as `1d226d6ddcd0c009b8f83367599d7a64521190f0` after GREEN CI, Authenticated Dashboard, Acquisition Scale, Refrigeration Browser and Offline Bundle gates.

Post-fix Raspberry Pi evidence:

`runtime/evidence/issue-289-20260817T080201Z-phase12b-postfix-r2`

Saved Live Dashboard verified:

- baseline `Live`, `websocket_clients=1`;
- sustained local transport outage reached truthful terminal `Offline` while retained values stayed visible;
- after path restoration, `websocket_clients=0` remained terminal until operator action;
- **Перепідключити** created one fresh WebSocket on the first poll;
- exactly one WebSocket remained stable for ten seconds;
- UI returned to `Live` without F5;
- Chromium NetworkService PID remained unchanged;
- physical acquisition advanced `6914 → 8376`;
- no Modbus/hardware write occurred.

## Raspberry Pi deployment capacity

The currently running runtime is healthy. A redundant post-reboot guarded redeploy on the same accepted head stopped safely **before runtime mutation** because the deployment capacity preflight reported:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

This is an operational constraint for the **next controlled redeploy**, not a failure of the currently running product. Do not bypass the capacity guard or delete product data/named volumes/evidence to create space. Any capacity recovery must remain bounded to explicitly disposable artifacts.

## Ready queue

Repository audit after closing #289 and #282 found **0 open `status:ready` Issues**.

Open Dependabot PRs remain separate dependency lanes and are not promoted to product work without their governing Issue/status and required verification.

Independent physical/evidence items already tracked elsewhere remain separate, including KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and Raspberry Pi version-management acceptance.

## Next action

Complete state-only Issue #497/PR reconciliation and merge only after GREEN state checks. After that there is no independent Ready Work Package; Sprint execution must stop at the repository Ready boundary until an existing backlog item is explicitly promoted to `status:ready` or a new focused product Work Package is created from a Product Owner priority.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
