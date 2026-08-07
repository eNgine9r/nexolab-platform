# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline merged into active branch: `main` at `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`
Last completed critical Work Package: Issue #374 / PR #375 — RS-485 serial EIO recovery
Active Work Package: Issue #368 / PR #373 — telemetry latest projection migration-v2/latest-query Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 completed

Issue #374 is closed as completed. PR #375 was squash-merged as `442cd6bc37aefc11977f82f31423d052fe70ced1`; post-merge state reconciliation PR #377 was subsequently merged into `main` as `1c10f86a57dbeea9b2d410888d57d8b19a2288ab`.

Completion remains:

```text
software verified; Raspberry Pi serial recovery hardware verified; merged
```

Controlled Raspberry Pi recovery evidence included PostgreSQL `max(id)` advancing `2327052 -> 2327095` in the first 10 seconds, Device Agent `status=ok`, MQTT connected, `last_error=null`, zero degraded/cooldown endpoints and no recent EIO/error matches.

## Active Issue #368

Issue #368 remains open `status:in-progress`; PR #373 remains Draft until physical acceptance completes.

The branch has now been reconciled with current `main` using merge commit:

```text
ad3923ace7aa8ae6bfe29548916d594171a5e50b
parents:
  cb082621f8b5e4cedf44534f3b5256fb2817d55a  (#368 verified software head)
  1c10f86a57dbeea9b2d410888d57d8b19a2288ab  (current main)
```

The merge retains the #368 telemetry projection/migration implementation and inherits the merged #374 Device Agent recovery plus canonical post-merge project state. No force push or history rewrite occurred.

Previous #368 software verification before the current-main reconciliation:

```text
cb082621f8b5e4cedf44534f3b5256fb2817d55a
26 completed checks
0 failures
0 in-progress
```

Fresh exact-head CI is now required on the reconciled branch. The previous GREEN result remains implementation evidence only; it is not substituted for the new candidate gate.

### Physical acceptance boundary

The previous Raspberry Pi migration-v2 retry did **not** establish a migration-v2 failure. Its freshness precondition rejected the run because Issue #374 had already stopped telemetry acquisition. Automatic rollback preserved:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

Acquisition freshness is now hardware verified by #374. After the reconciled #368 head is GREEN, the next action is controlled Raspberry Pi migration-v2/latest-query acceptance on the existing long-running PostgreSQL history.

Acceptance must prove:

- telemetry is fresh before migration;
- the long bulk backfill does not hold a long-lived exclusive ingestion lock;
- final cutover/catch-up is bounded;
- history and named volumes are preserved;
- projection cardinality is correct;
- startup deployment-gap reconciliation succeeds;
- `/api/v1/telemetry/latest?limit=1&offset=0` and normal latest reads are HTTP 200 with measured normal-load p95 `<500 ms`;
- central smoke passes without timeout/retry-budget increases;
- query plan reads `telemetry_latest`, not full retained history.

## Execution sequence

```text
#368 reconciled exact-head GREEN
  -> controlled Raspberry Pi migration-v2/latest-query acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, hardware write, data deletion, volume deletion, production/site cutover, polling amplification, mandatory cloud dependency or secret exposure is authorized by #368.

## Next action

Complete fresh exact-head CI and focused review/base audit on reconciled PR #373. If GREEN, run the controlled Raspberry Pi migration-v2/latest-query acceptance. Do not start #369 or #366 before #368 physical acceptance is complete.
