# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #389 / PR #429 — completed, no software blocker

Final exact head `a12c90968c736839991b88237033ee950c9ba707` passed 21/21
triggered workflows. PR #429 is squash-merged as
`83c77c934ed0c3356752dc11ce98247f243fa659`; Issue #389 is closed.

Physical Raspberry Pi update/rollback acceptance remains pending separately and
is not claimed by the software merge.

## Issue #430 — active state-only reconciliation

Only the focused four-file post-merge state update remains. No product/runtime
change is permitted.

## Ready/dependency audit

- No open Issue currently has `status:ready`.
- Issue #289 remains `status:needs-validation` pending a separately scoped #356
  route-prefetch/time-to-usable child and final physical measurement.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
