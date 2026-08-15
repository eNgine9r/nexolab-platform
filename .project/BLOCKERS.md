# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #465 / PR #470

No blocker remains. PR #470 was squash-merged as `8b7bb76115d11de0cc92cfaab2c131f27a891aa6` after all merge-authoritative exact-head workflows passed. Issue #465 is closed/completed and its stale `status:in-progress` label has been removed.

## Critical software blocker — Issue #468

Issue #468 is open, `priority:critical`, `status:ready` and selected as the next software Work Package after state-only #471.

Observed production failure: SQLite queue lock contention can terminate the Device Agent acquisition thread while the HTTP server/container remains reachable. This creates an unacceptable live-but-not-acquiring state with stale telemetry.

Issue #468 blocks truthful acquisition recovery and completion of the physical acceptance lane #289 until the software fix is merged and fresh controlled Raspberry Pi evidence proves an active worker and advancing telemetry freshness.

## Ready operational reliability issue — Issue #469

Issue #469 remains open, `priority:high`, `status:ready` and is ordered after #468.

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
