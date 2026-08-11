# NEXOLAB Current State

Updated: 2026-08-07

Verified repository baseline on `main`: `72f32d387e0199f7b863a56931d40a411ebf999c`

Active Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi migration-v2/latest-query acceptance

Active product epic: Issue #356 — eliminate visible loading across monitoring routes

Parallel acquisition/hardware epic: Issue #282

## Recently completed

### Issue #378 / PR #380 — RS-485 USB re-enumeration recovery

Completed and hardware verified. PR #380 squash-merged as `6645af46a198ff454142df3b0a713984f4d71196` after final exact-head `5635df201a6cbd59227a8ebe181c44fa5167f67c` completed 14 checks with 0 failures and 0 in-progress.

Controlled Raspberry Pi evidence proved same-container recovery across a real CP2104 disappearance and re-enumeration from `/dev/ttyUSB1` to `/dev/ttyUSB0`, with restart count `0 -> 0` and telemetry resuming in PostgreSQL. No Modbus write or hardware write was performed.

Issue #374 is the completed regression parent resolved by #378.

### Issue #381 / PR #382 — post-#378 state reconciliation

Completed. PR #382 merged as `329282496491d2ee27ab4f292e982a30af33c2b7` and closed Issue #381. The previous `.project` files incorrectly retained #381 as active after merge; Issue #387 exists solely to repair that stale state.

### Issue #383 / PR #384 — NEXOLAB Chart System technical specification

Completed. PR #384 squash-merged as `72f32d387e0199f7b863a56931d40a411ebf999c` after exact-head `51d7164e6b6453d4e15883d432fbd170de79b784` passed runtime-contract validation, ADR registry validation, dependency-policy validation, formatting, lint, typecheck, tests and production build.

The authoritative specification is `docs/architecture/nexolab-chart-system.md`.

It defines:

- one renderer-independent chart-domain boundary;
- separate measurement quality, delivery/freshness and continuity semantics;
- explicit fail-truthful data gaps;
- segment-aware min/max evidence-preserving reduction requirements;
- compatible-unit and axis policy;
- Live/Paused/Return-to-Live viewport semantics;
- common Chart Shell, cursor, inspector, legend, zoom/pan and event-overlay contracts;
- temperature, electrical, cumulative-energy, Test Session and report semantics;
- accessibility and responsive behavior;
- provisional Raspberry Pi browser performance budgets;
- a local-bundle renderer benchmark gate with no required CDN/cloud dependency.

No production chart code or dependency changed in #383/#384. Hardware acceptance was not claimed.

## Active Issue #368 / PR #373

PR #373 currently records software candidate:

```text
105ae34425a8937a6f61c172b52ce2c6fa09f3b3
26 completed checks
0 failures
0 in-progress
0 queued
```

That candidate was reconciled through then-current `main` at `329282496491d2ee27ab4f292e982a30af33c2b7`.

Current `main` has since advanced to `72f32d387e0199f7b863a56931d40a411ebf999c` through documentation-only PR #384. Before controlled Raspberry Pi migration-v2 acceptance, PR #373 must be reconciled again with current `main` and receive fresh exact-head GREEN CI. Do not assume the older exact-head result is sufficient for the new branch head.

The physical acceptance remains:

- recheck schema and acquisition freshness;
- create fresh PostgreSQL backup and checksum;
- run migration-v2 without a long exclusive advisory lock during initial backfill;
- prove ingestion continuity;
- complete bounded final delta catch-up;
- start the exact candidate Telemetry Service;
- validate projection cardinality;
- measure latest-query p95 below the accepted target;
- capture query-plan evidence using `telemetry_latest` rather than full retained history;
- preserve history and named volumes;
- perform no polling or hardware-write change.

## Critical execution sequence

```text
#368 current-main reconciliation + exact-head CI + controlled Raspberry Pi acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate Raspberry Pi validation track.

Issues #257 and #256 remain blocked/deferred by their existing ecosystem compatibility boundaries.

## Prepared Ready backlog

Issue #385 — local Raspberry Pi user administration and role management.

Issue #386 — chart-domain primitives and local renderer benchmark based on the merged Chart System specification.

Both are prepared `status:ready` packages. Neither is selected for implementation while the Sprint policy permits only one active implementation task and Issue #368 remains the critical selected Work Package.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is part of Issue #387 state reconciliation.

## Next action

Complete state-only Issue #387, then return immediately to Issue #368 / PR #373: reconcile with current `main`, rerun full exact-head CI and execute the controlled Raspberry Pi migration-v2/latest-query acceptance. The next chart implementation package remains Issue #386 and must not displace the current critical runtime sequence unless Sprint priority is explicitly changed by repository state or the Product Owner.
