# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #468 — software correction in PR #473

Issue #468 remains open and `status:in-progress` until PR #473 passes final exact-head verification and merges.

The focused implementation on head `4bb8ec501dae069240098f669b4d047b90c6bc47` addresses the observed SQLite lock-contention failure with bounded busy retry and process-level fail-closed supervision. Relevant pre-state workflows are GREEN.

This is not yet physical acceptance. Issue #289 remains blocked from completion until #468 is merged and fresh controlled Raspberry Pi/RS-485 evidence proves an active acquisition worker and advancing telemetry freshness after contention/recovery or fail-closed restart.

## Ready operational reliability issue — Issue #469

Issue #469 remains open, `priority:high`, `status:ready` and is ordered immediately after #468.

The current deployment evidence workflow can exhaust Raspberry Pi disk before updating `main`. The fix must add capacity preflight and bounded retention without deleting PostgreSQL, edge SQLite, MQTT, MinIO or named-volume product data.

#469 must be completed before relying on repeated controlled Pi deployment/evidence capture for final hardware acceptance.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 performance and recovery evidence is required. Software CI/Offline Bundle evidence does not satisfy hardware acceptance.

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
