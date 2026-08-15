# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #461 / PR #464 — pre-merge state reconciliation

No product/runtime blocker is known. The reusable hierarchical `TelemetryPointSelector` is product-verified on exact head `7a3dd97a2d406b8cd25680010da55a052edc0f74`.

Verified evidence on that head:

- CI `31891003782`: PASS;
- Authenticated Dashboard Acceptance `31891003701`: 15/15 PASS;
- Refrigeration Browser Acceptance `31891003707`: PASS;
- disconnected Offline Bundle `31891003946`: PASS;
- Acquisition Scale Acceptance `31891003741`: PASS for software matrices only.

The remaining merge barrier is process-only: commit the canonical `.project/**` checkpoint and repeat all required exact-head gates on the resulting final PR head. PR #464 must not be marked Ready or merged before that cycle is terminal GREEN and the final diff/review/main audit is clean.

## Issue #465 — blocked dependency

Issue #465 — Live Dashboard editor integration of `TelemetryPointSelector` — is created but remains `status:blocked` until Issue #461 is merged and post-merge project state is reconciled. It must be implemented on its own feature branch/PR and must not be folded into PR #464.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the controlled real Raspberry Pi/RS-485 performance and physical-request matrix. Software Acquisition Scale, browser and Offline Bundle evidence for #461 does not replace that physical evidence.

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
