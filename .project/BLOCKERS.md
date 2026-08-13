# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #433 / PR #434 — software verified, no CI blocker

Product head `1c138d0c87ea09847ea5d3311a11b405470a3682`
passed all 15 triggered checks; one image-attestation publish matrix entry was
intentionally skipped. Focused and complete local suites are also GREEN.
Review/merge remains pending, not blocked.

Post-change Raspberry Pi enrollment/recovery acceptance was not performed and
is not claimed. Any physical unplug/replug or sensor manipulation remains a
separate explicit user-assisted step.

## Issue #432 — ready after #433

Issue #432 remains `status:ready` and is sequenced after #433 is GREEN,
reconciled and merged. Do not mix its navigation/performance scope into #433.

## Ready/dependency audit

- Issue #432 is the selected next Ready package after #433.
- Issue #289 remains `status:needs-validation` pending #432 and final physical
  measurement.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
