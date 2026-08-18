# NEXOLAB Current State

Updated: 2026-08-18

## Repository and runtime baseline

Repository `main` is `31e1a191b472703aa1fad90de8e8c57406a5b802`, the squash merge of PR #591 reconciling Issue #584 real Raspberry Pi runtime acceptance.

The Raspberry Pi source runtime remains deployed at `7a19f53950492a40255c53b1d2018bbdff9466e2`. The persisted local AcquisitionRegistry remains revision 8 with `le01mp-201` intentionally `disabled` while W2 is externally owned. No source deployment was performed by Issues #584 or #586.

## Issue #584 — complete

Issue #584 and PR #591 are complete. Real Raspberry Pi evidence proved:

- AcquisitionRegistry revision `7 -> 8`;
- `le01mp-201` lifecycle `active -> disabled`;
- all 9 Unit 201 target definitions preserved;
- Unit 201 poll-eligible targets `9 -> 0`;
- Unit 201 scheduler jobs `9 -> 0`;
- Device Agent health `degraded -> ok`;
- Units 200/202/203 continued advancing;
- revision 8 and the disabled lifecycle persisted after restarting only `device-agent`.

Evidence: `runtime/deployments/issue-584-20260818T185455Z`.

## Issue #585 — blocked restoration lane

Do not restore Unit 201 until the Product Owner confirms that the external controller no longer owns W2 and explicitly approves any required physical handback. The 2026-08-21 through 2026-08-23 review window is not authorization by itself.

## Issue #586 — implementation complete, final PR validation in progress

Real Raspberry Pi browser-closed evidence proved the acquisition and persistence planes are independent of browser lifetime before any #586 code change:

- 60 sampled checks observed zero established browser/API connections on ports 3000/8081/8082;
- AcquisitionRegistry remained `8 -> 8`;
- Device Agent `normal.physical_requests_total` advanced `5049 -> 5392` (`+343`);
- PostgreSQL `telemetry_samples` advanced `4,665,493 -> 4,665,722` (`+229`);
- newest persisted `captured_at` advanced from `2026-08-18 19:18:52.033946+00` to `2026-08-18 19:20:28.276628+00`.

Evidence: `runtime/deployments/issue-586-browser-closed-20260818T191852Z`.

The defect was therefore isolated to the Overview persisted-history bootstrap/reconciliation path rather than Device Agent, MQTT or PostgreSQL persistence.

PR #592 implements the focused repair:

- one canonical complete-history loader with stable `snapshot_at`, captured-time pagination and event deduplication;
- Live Data reuses that loader instead of maintaining a second pagination implementation;
- Overview no longer treats one `limit=1000` page as complete history;
- latest/WebSocket overlap is buffered during history bootstrap and reconciled deterministically;
- duplicate and out-of-order live tail records are rejected;
- newer non-valid samples remain available to the canonical Chart System so real gaps remain truthful;
- Overview chart input no longer concatenates a second route-local latest buffer after history reconciliation.

Core CI run `32179097680` is PASS for formatting, lint, TypeScript, full tests and production build on the pre-checkpoint implementation head. The final checkpoint commit intentionally requires the required CI/runtime/offline gates to run again before merge.

No backend schema, acquisition scheduler, physical polling cadence, dependency graph, Modbus behavior or hardware configuration changed in #586.

## Current execution boundary

Active Work Package: **Issue #586 — Prove and repair persistent telemetry history across browser-offline intervals**.

Merge PR #592 only after the final head is GREEN for required CI, Authenticated Dashboard Acceptance and Offline Bundle. After GREEN merge and state reconciliation, Issue #587 becomes the next independent Ready Work Package.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
