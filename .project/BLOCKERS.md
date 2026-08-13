# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #366 / PR #423 — completed, no blocker

The Overview alerts read-model duplicate proven by Authenticated Dashboard #1676
is corrected in product/state commit
`625355c988a286bd007e9c84c48384f2473c0ba6`. Canonical local Authenticated Dashboard acceptance passed
12/12 scenarios with one active and one acknowledged exact alert query across the
full route cycle, one WebSocket maximum concurrent, and zero acquisition
mutations.

Final head `11a58e99a69ec04eea38316553724cdad4c83493` passed CI, all relevant
browser gates, Offline Auth and Offline Bundle. PR #423 is squash-merged as
`a8daee3468e2384c505f988eb006fca05c2afa3f`; Issue #366 is closed.

## Issue #427 — active state-only reconciliation

The only remaining #366 continuity work is the focused five-file post-merge
state/audit reconciliation. No product/runtime code is permitted.

## Local harness note — not a product blocker

Direct `run-authenticated-dashboard-acceptance.sh` invocation first exposed an
uppercase auto-generated Compose project name rejected by the installed Compose
version, then the missing acquisition fixture required by the dashboard config.
The canonical `run-acquisition-invariant-browser-acceptance.sh` entrypoint with a
lowercase isolated project name passed. No runtime product defect was observed.

## Downstream and independent lanes

- Issue #289 remains `status:needs-validation` pending a separately prepared
  focused #356 route-prefetch/time-to-usable slice and final hardware matrix.
- Issue #389 is the next independently Ready package after #427 merges.
- Issue #415 remains an open Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
