# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #433 — locally verified, exact-head workflows pending

The implementation has no local software blocker. Focused and complete Device
Agent/frontend suites, formatting, lint, typecheck and production build pass.
The focused PR and its exact-head GitHub/offline/browser gates remain pending.

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
