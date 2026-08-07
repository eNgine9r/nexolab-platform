# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `329282496491d2ee27ab4f292e982a30af33c2b7`
Active Work Package: Issue #368 / PR #373 — telemetry latest projection Raspberry Pi migration-v2/latest-query acceptance
Completed recovery Work Package: Issue #378 / PR #380 — RS-485 USB re-enumeration recovery
Resolved regression parent: Issue #374 / PR #375
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #378 / #374 recovery chain — completed

Issue #378 / PR #380 is merged and Raspberry Pi hardware verified. The same running Device Agent recovered real telemetry after CP2104 disconnect/re-enumeration from `ttyUSB1` to `ttyUSB0` with unchanged container identity/start time and restart count `0 -> 0`. Issue #374 is closed as the completed regression parent.

## Active Issue #368 / PR #373

PR #373 has now been reconciled with current `main` through non-force two-parent merge commit:

```text
3427df41fab06667904d127313723fa90e130fcd
parents:
  36ccb909ca3754cc395468382bed2da93743ee24
  329282496491d2ee27ab4f292e982a30af33c2b7
```

The reconciliation tree is based on current `main` and overlays only the ten telemetry-specific #368 files. Therefore all merged #378 runtime/state changes are inherited canonically while the #368 telemetry implementation remains intact. No rebase, force push or `main` mutation was used.

The previous `36ccb909...` CI record is historical only. Repository state had recorded it as GREEN, while current workflow-run history exposes older failed runs on that SHA; this discrepancy is intentionally superseded. **Only fresh exact-head CI on the branch head containing this checkpoint is authoritative before Raspberry Pi acceptance.**

### #368 implementation boundary

- durable `telemetry_latest` projection keyed by canonical series identity;
- immutable telemetry history retained;
- transactional history/latest persistence;
- duplicate idempotency;
- out-of-order samples cannot regress latest state;
- deterministic equal-timestamp `sample_id` tie-break;
- latest API reads bounded projection rather than retained history;
- migration-v2 performs long initial backfill before exclusive advisory lock and bounded delta catch-up under final lock;
- startup deployment-gap reconciliation is bounded and fail-closed;
- no Device Agent, scheduler, polling cadence or Modbus behavior changes.

### Raspberry Pi pre-migration state

Last verified safe physical database state remains:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
advisory locks: none
```

This is historical preflight evidence and must be rechecked immediately before migration. Acquisition must also be fresh (`newest_age <= 120 s`) before migration-v2 is allowed to start.

### Physical acceptance gate after software GREEN

- exact candidate SHA verification;
- fresh PostgreSQL backup and checksum;
- current acquisition freshness proof;
- migration-v2 backfill while ingestion continues;
- no long-lived exclusive advisory lock during initial backfill;
- bounded final delta catch-up/cutover;
- schema `20260807_0023` and projection cardinality correctness;
- exact candidate Telemetry Service startup;
- repeated latest-query latency with normal-load p95 `<500 ms`;
- query-plan evidence proving latest reads use `telemetry_latest`, not retained full history;
- central smoke and final history/volume/freshness audit.

## Execution sequence

```text
fresh exact-head #368 CI
  -> controlled Raspberry Pi migration-v2/latest-query acceptance
  -> final state/review audit and merge #373
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, polling cadence change, data deletion, volume deletion, privileged container, production/site cutover, mandatory cloud dependency or secret exposure is part of #368 software reconciliation.

## Next action

Freeze branch content after the four-file #368 checkpoint. Require full fresh exact-head CI to complete GREEN. Only then run the corrected child-shell Raspberry Pi migration-v2/latest-query acceptance; do not run migration from an older candidate.
