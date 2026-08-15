# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #468 — software blocker resolved, physical acceptance pending

Issue #468 is closed and PR #473 is squash-merged at `d06b7958eab08d8ce319b3f3397ac541079e7f68`.

The software fix passed all final exact-head gates, including CI, Device Agent Fleet, Acquisition Scale, disconnected Offline Bundle, Authenticated Dashboard, MQTT TLS Fleet, Disaster Recovery TLS Fleet, Container Supply Chain and Edge image.

This resolves the repository software blocker. It does **not** close the physical acceptance lane: Issue #289 still requires fresh Raspberry Pi/RS-485 evidence proving an active acquisition worker and advancing telemetry freshness after recovery or fail-closed restart.

## Ready operational reliability issue — Issue #469

Issue #469 remains open, `priority:high`, `status:ready` and is the next software Work Package after state-only Issue #474.

The controlled deployment path can exhaust Raspberry Pi disk while archiving deployment evidence before updating `main`. The fix must add free-space/capacity preflight and deterministic bounded retention for explicitly classified deployment-generated evidence/build caches only.

Automated cleanup must never delete PostgreSQL, edge SQLite, MQTT, MinIO, named Docker volumes or other product data. The newest failure evidence and current acceptance evidence must be preserved.

Issue #469 must complete before repeated controlled Raspberry Pi deployment/evidence capture is treated as reliable for final hardware acceptance.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 performance and recovery evidence is required after #469. Software CI/Offline Bundle evidence does not satisfy hardware acceptance.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Hard safety blockers

The following actions remain outside current authorization and require explicit approval where applicable:

- Modbus writes or controller configuration changes;
- hardware writes or actuator control;
- destructive persistent-data or volume deletion;
- production/site cutover;
- secret/billing/DNS changes.

LOCAL_LAN, offline-first runtime and read-only acquisition boundaries remain unchanged.
