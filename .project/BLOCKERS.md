# NEXOLAB Blockers

Updated: 2026-08-14

## Issue #451 / PR #452

No software, CI, browser or offline-runtime blocker remains on the verified
product head `58639a3a19ff7ef13e37d3c2de23adf4b9c3bc02`.

Exact-head product verification is GREEN:

- CI / Quality and build: PASS;
- Authenticated Dashboard Acceptance: 13/13 PASS;
- Refrigeration Browser Acceptance: PASS;
- disconnected Offline Bundle: PASS with clean transferred-host startup,
  blocked egress, update/rollback and persistent-volume preservation.

Current procedural blocker before merge: complete this state-only reconciliation,
run the same mandatory exact-head gates on the resulting final PR head, then
perform the Ready/final merge audit. This is not a product defect blocker.

Raspberry Pi operator acceptance for Issue #451 remains **pending** and must not
be claimed from software/browser CI evidence.

## Issue #453 dependency blocker

Issue #453 — equipment-centric multi-metric charts with dynamic Y axes — is
intentionally blocked by Issue #451 until PR #452 is merged. It must remain a
separate Issue/feature branch/PR and must not be folded into #451.

## Independent hardware lane — Issue #289

Issue #289 remains open and in progress. Completion still requires controlled
real Raspberry Pi/RS-485 evidence. The #451 chart work does not close or replace
that hardware-performance acceptance lane.

Residual physical evidence from the worker-liveness investigation remains
truthful context for #289, including timeout/retry/missed-deadline/deferred
behavior. The pre-fix zero-request phase is defect evidence only and must not be
reused as a passing baseline.

## Other pending hardware evidence

- Issue #445 / PR #446: software/CI/offline verified; Raspberry Pi KK2/Unit 115
  field retest remains pending.
- Issue #447 / PR #448: software/browser/offline verified; Raspberry Pi
  perceived-latency acceptance remains pending.
- Issue #389: physical Raspberry Pi version-management acceptance remains
  pending separately.

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
