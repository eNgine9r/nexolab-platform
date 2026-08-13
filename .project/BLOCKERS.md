# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #433 / PR #434 — merged

PR #434 is squash-merged as `06f78b178acfed72033bf607099d827eca1a9f9a`.
Final PR head `236019f9929aa230ff1f2f6ff0954ecee3bde6f1` passed 15 exact-head
checks. Disconnected Offline Bundle runtime passed; one attestation publish
matrix entry was intentionally skipped.

Post-change Raspberry Pi enrollment/recovery acceptance was not performed and
is not claimed.

## Issue #432 — selected Ready Work Package

Issue #432 is the only open `status:ready` product package in the fresh audit
and is selected next after this state-only reconciliation.

## Ready/dependency audit

- Issue #432 is selected next.
- Issue #289 remains `status:needs-validation` pending #432 and final physical measurement.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.
- Raspberry Pi version-management acceptance for #389 remains pending separately.

## Safety

Existing LOCAL_LAN, offline-runtime, read-only acquisition and hardware-safety
boundaries remain unchanged.
