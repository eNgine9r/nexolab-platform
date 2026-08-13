# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #389 — no software blocker

The local version-management implementation is software-verified. It stops on
unknown or unsafe package/runtime evidence, requires a verified PostgreSQL
backup before mutation, preserves persistent storage and exposes no arbitrary
host command surface.

Physical Raspberry Pi update/rollback acceptance remains pending as a separate
lane; this checkpoint makes no unsupported hardware claim.

## Downstream lanes

- Issue #289 remains `status:needs-validation` pending a separately scoped #356
  route-prefetch/time-to-usable slice and final physical measurement.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
