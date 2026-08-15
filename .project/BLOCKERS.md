# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #469 — software candidate ready for exact-head verification, physical acceptance pending

Issue #469 is open, `priority:high`, `status:in-progress`; draft PR #476 contains the focused deployment-capacity correction.

The software candidate adds bounded timestamped deployment-evidence retention, conservative preflight/recheck capacity gates, fail-closed PostgreSQL size measurement and atomic large evidence writes. Targeted deterministic tests are GREEN.

Final exact-head CI after the canonical `.project/**` checkpoint is still required before software merge.

Physical acceptance remains unresolved: after software merge a controlled Raspberry Pi deployment must prove capacity diagnostics, safe bounded evidence cleanup, preserved named-volume/product-data identities and exact current `main`. Software CI does not satisfy this requirement.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 performance and recovery evidence is required. Its completion remains dependent on the #469 deployment path being physically accepted.

## Other pending physical evidence

- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Hard safety blockers

The following actions remain outside current authorization and require explicit approval where applicable:

- Modbus writes or controller configuration changes;
- hardware writes or actuator control;
- destructive product persistent-data or named-volume deletion;
- production/site cutover;
- secret/billing/DNS changes.

Bounded retention of old timestamped `runtime/deployments/*` evidence is intentionally isolated from product data. The current deployment, newest evidence and `.nexolab-preserve` evidence are protected.

LOCAL_LAN, offline-first runtime and read-only acquisition boundaries remain unchanged.
