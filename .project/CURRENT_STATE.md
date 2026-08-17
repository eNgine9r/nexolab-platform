# NEXOLAB Current State

Updated: 2026-08-17

## Repository and deployed baseline

The accepted/deployed product/runtime baseline remains `1d226d6ddcd0c009b8f83367599d7a64521190f0`, the squash merge of PR #496 — **restart terminal shared telemetry transport**.

The repository baseline used for this state selection is `b7b0df6bd49e8416b2073a83310b4eb2aa0468c3`, the merge of PR #498. Issue #497 and PR #498 are completed. Issue #499 is the focused state-only reconciliation that removes the stale #497 active marker and promotes the next Product Owner-approved critical Work Package.

The controlled Raspberry Pi `LOCAL_LAN` runtime is healthy on the accepted product head:

- deployment evidence: `runtime/deployments/20260817T074249Z`;
- runtime mode: `lan`;
- bind address: `172.18.48.34`;
- dashboard: `http://172.18.48.34:3000`;
- API: `http://172.18.48.34:8082`;
- central PostgreSQL/MQTT/Telemetry healthy;
- edge MQTT/Device Agent healthy;
- one active serialized RS-485 bus worker.

No product/runtime redeploy is part of Issue #499.

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

## Issue #493 — completed and hardware verified

PR #496 merged as `1d226d6ddcd0c009b8f83367599d7a64521190f0` after GREEN CI, Authenticated Dashboard, Acquisition Scale, Refrigeration Browser and Offline Bundle gates.

Post-fix Raspberry Pi evidence:

`runtime/evidence/issue-289-20260817T080201Z-phase12b-postfix-r2`

## Raspberry Pi deployment capacity

The currently running runtime is healthy. A redundant post-reboot guarded redeploy on the same accepted head stopped safely **before runtime mutation** because the deployment capacity preflight reported:

- `free_bytes=15310114816`;
- `required_bytes=16595036807`;
- `reserve_bytes=2147483648`.

This is a soft operational constraint for the **next controlled redeploy**, not a failure of the currently running product. Do not bypass the capacity guard or delete product data, PostgreSQL history, named volumes or acceptance evidence. Any recovery must remain bounded to explicitly disposable artifacts and be verified before deployment.

## Ready queue after Product Owner priority decision

The Product Owner explicitly approved continuing through the remaining backlog by criticality.

The single selected next Ready Work Package is:

**Issue #444 — Restore LOCAL_LAN user administration API availability** (`priority:critical`).

Expected outcome:

- full `create_app` local-auth composition exposes `/api/v1/admin/users`;
- administrator list/create path works locally;
- non-admin remains server-side forbidden;
- deployment/runtime contract fails closed when LOCAL_LAN local-auth is expected but admin routes are absent;
- route/profile mismatch is diagnosed explicitly instead of a generic API error;
- local identities remain local and offline-capable;
- no secret activation is performed without separate Product Owner action.

Next critical ordering after #444, subject to fresh dependency/blocker audit at each boundary:

1. #355 — Live Dashboard canonical inventory without telemetry-history timeout;
2. #357 — refrigeration Raspberry Pi perceived-latency closeout;
3. #189 — backup/restore/rollback/power-loss recovery acceptance;
4. #450 — chart reliability, Live Data UX and hierarchical telemetry selection Epic.

Stale state-only trackers #416 and #449 are superseded by later accepted repository state and should not remain active backlog work.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, production/site cutover, product persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
