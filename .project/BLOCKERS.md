# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #465 / PR #470 — final merge gate

No product/runtime blocker is currently known.

Issue #465 implementation is complete on `feat/465-live-dashboard-telemetry-selector`. Exact product head `34dbc2fb2936940e5193aabc2898fefe5bf3c984` is software/browser/offline GREEN across CI, Telemetry service, authenticated production browser, refrigeration browser, offline bundle/auth and related runtime acceptance workflows.

The first Authenticated Dashboard attempt on that same product tree observed a one-off pre-existing multi-axis WebSocket peak of 2. The #465 Live Dashboard and hierarchical-selector scenarios passed in that attempt. No #465 product code was changed for the unrelated result; a failed-job rerun on the exact same commit/tree passed all 15 production scenarios. This is therefore recorded as a transient CI race, not an open #465 regression.

The only remaining barrier before merge is process/verification: the final `.project/**` checkpoint head must pass exact-head required checks and a clean main/diff/review/mergeability audit. PR #470 remains Draft until that gate is complete.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the controlled real Raspberry Pi/RS-485 performance and physical-request matrix. Software Acquisition Scale, browser, backend and Offline Bundle evidence from #465 does not replace that physical evidence.

## Other pending hardware evidence

- KK2/Unit 115 field retest remains pending;
- refrigeration perceived-latency acceptance remains pending;
- physical Raspberry Pi version-management acceptance remains pending.

## Hard safety blockers

The following actions remain outside current authorization and require explicit approval where applicable:

- Modbus writes or controller configuration changes;
- hardware writes or actuator control;
- destructive persistent-data or volume deletion;
- production/site cutover;
- secret/billing/DNS changes.

LOCAL_LAN, offline-first runtime and read-only acquisition boundaries remain unchanged.
