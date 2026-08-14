# NEXOLAB Blockers

Updated: 2026-08-14

## Issue #453 / PR #456 — no known software/runtime blocker

Issue #453 is active and PR #456 has product-head verification GREEN on
`3e7f9d8cac8da1b8a34fdf62053b6fe3a7bf3e79`:

- CI: PASS;
- Authenticated Dashboard Acceptance: 14/14 PASS;
- Refrigeration Browser Acceptance: PASS;
- Acquisition Scale Acceptance: PASS;
- disconnected Offline Bundle: PASS, including clean transferred-host startup,
  blocked egress, update/rollback and persistent-volume preservation.

The remaining boundary is procedural and exact-head based: this state-only
reconciliation commit creates a new PR head, so required gates must run again on
that exact head before Ready/merge. Final audit must also confirm current `main`,
focused diff and unresolved-review state.

Raspberry Pi operator acceptance remains **pending** and is not claimed. It does
not convert software/browser/offline evidence into physical hardware acceptance.

## Issue #454 / PR #455 — completed

The former procedural blocker is resolved. Issue #454 is closed and PR #455 was
squash-merged into `main` as
`058ddf8131d43e0b8ea56553bff83fbe0b90efa0` from final head
`af92129a03591e10dab594f9cfe1dfcfe16256c0`.

## Issue #457 — intentionally blocked on #453 merge

Issue #457 is the next graph-first Live Data Work Package from Epic #450. It is
created with `status:blocked` and must remain blocked until #453 / PR #456 is
merged. No #457 implementation belongs in PR #456.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the
controlled real Raspberry Pi/RS-485 performance and physical-request matrix.
The software Acquisition Scale workflow for #453 does not replace that real
hardware evidence.

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
