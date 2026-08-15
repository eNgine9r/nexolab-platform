# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #462 — state-only reconciliation

No product/runtime blocker is known. Issue #462 exists only because the final
`.project/**` checkpoint in PR #460 was created before merge and therefore must
be reconciled to the actual post-merge GitHub state.

Scope is limited to the four canonical `.project` files. Exact-head CI must be
GREEN before merge.

## Issue #461 — Ready

Issue #461 — reusable hierarchical `TelemetryPointSelector` — is open, assigned
and `status:ready`. Its dependency on #457 is resolved. Implementation must wait
until the state-only #462 reconciliation is merged, then proceed on its own
feature branch/PR.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the
controlled real Raspberry Pi/RS-485 performance and physical-request matrix.
Software/browser/offline verification for #457 does not replace that evidence.

## Other pending hardware evidence

- KK2/Unit 115 field retest remains pending;
- refrigeration perceived-latency acceptance remains pending;
- physical Raspberry Pi version-management acceptance remains pending.

## Hard safety blockers

The following actions remain outside current authorization and require explicit
approval where applicable:

- Modbus writes or controller configuration changes;
- hardware writes or actuator control;
- destructive persistent-data or volume deletion;
- production/site cutover;
- secret/billing/DNS changes.

LOCAL_LAN, offline-first runtime and read-only acquisition boundaries remain
unchanged.
