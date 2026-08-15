# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #465 / PR #470 — final merge gate

No product/runtime blocker is currently known.

Issue #465 implementation is complete on `feat/465-live-dashboard-telemetry-selector`. Full operator/browser/offline behavior was verified on trusted product head `34dbc2fb2936940e5193aabc2898fefe5bf3c984`, and subsequent deterministic PostgreSQL query-plan evidence hardening is verified on `74e5e867f7738a24cfc5960bd5b4a32e7e1682fa`.

The earlier PostgreSQL failure on state-checkpoint head `d217bf8403925d46d419c89017323d6f35008dfd` was not a runtime regression: 445 backend tests passed and the inventory query executed in 0.502 ms, but PostgreSQL selected a cheaper natural plan that did not print the expected index name. The #465 evidence test was corrected to separate normal bounded-runtime evidence from an index-preferred EXPLAIN that deterministically proves the `ix_telemetry_latest_lookup` path. On hardened head `74e5e867f7738a24cfc5960bd5b4a32e7e1682fa`, CI and Telemetry service are GREEN, including the full backend suite, PostgreSQL outage recovery, offline migration validation and container build.

The only remaining barrier before merge is process/verification: this final `.project/**` checkpoint head must pass exact-head required checks and a clean main/diff/review/mergeability audit. PR #470 remains Draft until that gate is complete. No further file change is planned unless a factual defect is found.

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
