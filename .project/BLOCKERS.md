# NEXOLAB Blockers

Updated: 2026-08-13

## Issue #366 / Draft PR #423 — active, no product blocker

The Overview alerts read-model duplicate proven by Authenticated Dashboard #1676
is corrected in product/state commit
`625355c988a286bd007e9c84c48384f2473c0ba6`. Canonical local Authenticated Dashboard acceptance passed
12/12 scenarios with one active and one acknowledged exact alert query across the
full route cycle, one WebSocket maximum concurrent, and zero acquisition
mutations.

Remaining gates are procedural/exact-head verification:

- push the committed alerts slice;
- require GREEN exact-head CI, browser and offline gates;
- review the final focused diff and resolve review threads;
- reconcile the Issue #366 audit and project state before Ready/merge.

## Local harness note — not a product blocker

Direct `run-authenticated-dashboard-acceptance.sh` invocation first exposed an
uppercase auto-generated Compose project name rejected by the installed Compose
version, then the missing acquisition fixture required by the dashboard config.
The canonical `run-acquisition-invariant-browser-acceptance.sh` entrypoint with a
lowercase isolated project name passed. No runtime product defect was observed.

## Downstream and independent lanes

- Issue #289 remains downstream of #366.
- Issue #389 remains independent Ready/not selected.
- Issue #415 remains an open Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus
or other hardware writes, secret exposure, mandatory online runtime dependencies,
privileged hardware containers or unsupported physical-acceptance claims.
