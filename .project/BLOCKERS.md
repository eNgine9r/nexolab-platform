# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #466 — state-only post-merge reconciliation

No product/runtime blocker is known.

Issue #461 is closed and PR #464 is merged as `30659fb22e6420863383071079a5a40a6b6cd0d8` from final exact verified head `a49ee1a92546a04d8ae5c2b47d4a3d01b882ee56`.

The previously reported assistant execution-layer merge blocker for PR #464 is resolved by the completed GitHub merge and is no longer open.

The remaining barrier before the next software feature is process-only: Issue #466 must change only the four canonical `.project/**` files, pass exact-head state-only CI, and complete a clean diff/review/main audit before squash merge.

## Issue #465 — temporary state-reconciliation dependency

Issue #465 — Live Dashboard editor integration of `TelemetryPointSelector` — has its product dependency on #461 resolved. It remains `status:blocked` only until Issue #466 is merged.

After #466 merge, #465 should move to `status:ready`; implementation must occur on its own feature branch/PR and must not be folded into the state-only reconciliation.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the controlled real Raspberry Pi/RS-485 performance and physical-request matrix. Software Acquisition Scale, browser and Offline Bundle evidence does not replace that physical evidence.

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
