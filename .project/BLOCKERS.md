# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #433 / PR #434 — merged

PR #434 is squash-merged as `06f78b178acfed72033bf607099d827eca1a9f9a`.
Final PR head `236019f9929aa230ff1f2f6ff0954ecee3bde6f1` passed 15 exact-head
checks. Disconnected Offline Bundle runtime passed; one attestation publish
matrix entry was intentionally skipped.

Post-change Raspberry Pi enrollment/recovery acceptance was not performed and
is not claimed.

## Issue #432 / PR #437 — software/browser verified

PR #437 is open. Review-corrected warm navigation passed at `201..398 ms` median across the six
canonical routes with one document load, `websocket_max_concurrent = 1`, no
eager full-inventory fetch, no retained equipment/layout read growth across warm
remounts and zero acquisition mutations. Exact evidence head
`5390bc42cde8de6885267eabe3df421fa32b7266` passed the required local software,
browser and offline gates, including disconnected Offline Bundle update/rollback
volume preservation. Exact-head Offline Auth passed on rerun after an initial
runner image-pull failure before the migration test executed.

No Issue #432 implementation blocker remains. Raspberry Pi performance evidence
is intentionally deferred to Issue #289 and is not claimed.

## Ready/dependency audit

- Issue #432 / PR #437 has all actionable P2 review findings implemented; final
  exact-head verification and thread resolution are the remaining pre-merge actions.
- Issue #289 remains `status:needs-validation` pending the #432 merge and final physical measurement.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.
- Raspberry Pi version-management acceptance for #389 remains pending separately.

## Safety

Existing LOCAL_LAN, offline-runtime, read-only acquisition and hardware-safety
boundaries remain unchanged.
