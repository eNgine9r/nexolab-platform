# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `6645af46a198ff454142df3b0a713984f4d71196`
Active Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi migration-v2/latest-query acceptance
Completed recovery Work Package: Issue #378 / PR #380 — RS-485 USB re-enumeration recovery
Resolved regression parent: Issue #374 / PR #375
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #378 / PR #380 — completed and hardware verified

PR #380 was squash-merged into `main` as `6645af46a198ff454142df3b0a713984f4d71196` after final exact-head `5635df201a6cbd59227a8ebe181c44fa5167f67c` completed 14 GitHub checks with 0 failures and 0 in-progress.

The merged recovery includes:

- live read-only host `/dev` visibility at `/host/dev` instead of static Docker device-node injection;
- exact `/dev/serial/by-id/...` identity across changing `ttyUSB` minors;
- bounded `c 188:* rwm` cgroup permission with no privileged container;
- `(OSError, termios.error)` transport-failure handling;
- failed cached serial-handle invalidation and best-effort close while preserving the original exception;
- reopen only on the next normal scheduler attempt;
- preserved FC03 read-only behavior, scheduler cadence and one serialized worker per bus.

Controlled Raspberry Pi hardware acceptance passed:

```text
container before/after: 9f03df0e798e
started_at before/after: unchanged
restart_count: 0 -> 0
stable by-id path disappeared: yes
device_before: /dev/ttyUSB1
stable by-id path reappeared: yes
device_after: /dev/ttyUSB0
PostgreSQL max(id) at reappearance: 2332589
first recovery max(id): 2332595
final observed max(id): 2332624
newest_age after recovery: ~18-21 s
```

Transient EIO/ENOENT warnings occurred only while the adapter/path was physically absent. Acquisition recovered automatically on the same running Device Agent.

## Issue #374 regression status — resolved

Issue #374 / PR #375 remains the merged first serial-session invalidation slice. The later long-duration USB re-enumeration regression exposed during #368 acceptance is now resolved by merged #378 and its physical hardware evidence. Issue #374 can be closed as completed regression parent after this state-only reconciliation is merged.

## Active Issue #368 / PR #373

Issue #368 remains software-GREEN on its previously reconciled head:

```text
36ccb909ca3754cc395468382bed2da93743ee24
26 completed GitHub checks
0 failures
0 in-progress
0 queued
```

Because `main` now contains #378, PR #373 must first be reconciled with current `main` and rerun full exact-head CI before any physical migration is attempted.

The Raspberry Pi database remains safe before migration-v2:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

The corrected #368 physical gate remains:

- fresh PostgreSQL backup;
- acquisition freshness proven before migration;
- migration-v2 backfill without long exclusive advisory lock;
- ingestion continuity during backfill;
- final bounded delta catch-up;
- candidate Telemetry Service startup;
- projection cardinality validation;
- latest-query p95 and query-plan verification;
- no polling changes and no destructive operations.

## Execution sequence

```text
post-#378 state reconciliation
  -> reconcile PR #373 with current main
  -> full exact-head #368 CI
  -> controlled Raspberry Pi migration-v2/latest-query acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is part of this state-only reconciliation.

## Next action

Run proportional exact-head CI and focused review/base audit for state-only Issue #381. If GREEN, merge it, close #374 as completed regression parent, then reconcile PR #373 with current `main` and resume Issue #368 acceptance.
