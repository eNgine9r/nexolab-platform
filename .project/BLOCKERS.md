# NEXOLAB Blockers

Updated: 2026-08-14

## Issue #451 / PR #452 — merged, no software blocker

Issue #451 is closed/completed and PR #452 is squash-merged as
`6286e8ed4ccb3d5d0e5f34d7b62fd6cb15fdedc0` from final PR head
`795cff9a309fcb70981293c29009682fdafddfba`.

Final exact-head verification is GREEN:

- CI / Quality and build: PASS;
- Authenticated Dashboard Acceptance: 13/13 PASS;
- Refrigeration Browser Acceptance: PASS;
- disconnected Offline Bundle: PASS with clean transferred-host startup,
  blocked egress, update/rollback and persistent-volume preservation.

No software, CI, browser or offline-runtime blocker remains for #451.
Raspberry Pi operator acceptance remains **pending** and is not claimed.

## Issue #453 dependency blocker — resolved by #451 merge

The product dependency `#453 -> #451` is resolved by merge `6286e8ed...`.
Issue #453 remains temporarily labelled `status:blocked` only until the state-only
Issue #454 reconciliation merges. After that procedural boundary it may move to
`status:ready` and start on its own feature branch/PR.

No runtime or architecture blocker is currently identified for #453.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires
controlled real Raspberry Pi/RS-485 evidence. The #451 chart work and #454 state
reconciliation do not close, replace or satisfy that hardware-performance gate.

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
