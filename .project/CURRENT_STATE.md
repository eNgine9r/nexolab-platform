# NEXOLAB Current State

Updated: 2026-08-11

Verified repository baseline on `main`: `810f6a6b48fc3ce04eeb1174236df3bd5ed53380`.

Active Work Package: Issue #368 / PR #373 — final repository reconciliation and exact-head CI after successful Raspberry Pi physical acceptance.

## Issue #368 — physical acceptance PASS

The frozen candidate `105ae34425a8937a6f61c172b52ce2c6fa09f3b3` passed the controlled Raspberry Pi migration-v2/latest-query acceptance on the existing long-running PostgreSQL database.

Measured evidence:

```text
migration 20260805_0022 -> 20260807_0023: rc=0, 330 s
ingestion remained live during backfill
projection rows / canonical series: 194 / 194
latest limit=1 p95:      0.013076 s
latest default p95:      0.023364 s
latest limit=100 p95:    0.015271 s
filtered series p95:     0.011519 s
query plan: ix_telemetry_latest_order on telemetry_latest
query execution: 0.136 ms
central smoke: PASS
final advisory lock audit: 0 granted exclusive / 0 waiting
PostgreSQL volume: nexolab-central-postgres-data preserved
Device Agent: ok, MQTT connected, no degraded/cooldown endpoints
```

The original controlled-host latest request exceeded 20 seconds. The physical candidate now answers normal latest reads in milliseconds without scanning retained history.

No Modbus write, hardware write, telemetry truncation, history deletion or volume deletion occurred.

## Repository reconciliation

Current `main` advanced to `810f6a6b48fc3ce04eeb1174236df3bd5ed53380` after the physical candidate was frozen. Those intervening repository changes contain no telemetry-service runtime overlap with #368.

PR #373 has therefore been reconciled by two-parent commit `202afcb3f3d31bcabdcb3ed32edcc37505a77c26`, using current `main` as the base tree and overlaying only the ten physically verified #368 telemetry implementation/test files.

This state checkpoint is the only content change after that merge-tree. A fresh exact-head CI run is mandatory before Ready/merge.

## Alembic ordering hazard with Issue #385

Issue #385 / PR #390 is software verified at `8bb31364a7523164fab95c29aef9d8a839283213`, but its unmerged migration also uses revision `20260807_0023` based on `20260805_0022`.

The controlled production Raspberry Pi database now records `20260807_0023` as the #368 telemetry projection migration. Merging #385 first would make the repository assign different schema meaning to the same revision id and could cause Alembic to skip the #385 permission migration on that database.

Safe ordering is therefore:

```text
#368 final CI -> merge as canonical 20260807_0023
-> #385 reconcile with post-#368 main
-> renumber #385 migration to 20260807_0024, down_revision=20260807_0023
-> fresh #385 exact-head CI
-> isolated Raspberry Pi Users & Access acceptance
-> #385 merge
-> #389 Version Management
```

This is a critical-bug interruption of the Product Owner-selected #385 feature, not a cancellation or reprioritization away from Users & Access.

## Downstream runtime sequence

After the selected user-management/version lane, resume:

```text
#369 -> #366 -> #289
```

Issue #245 remains a separate Raspberry Pi validation track. Issue #386 remains prepared but not selected. Issues #257 and #256 remain blocked/deferred by their ecosystem compatibility boundaries.

## Current safety boundary

Do not run `deploy-current-head` on the controlled Pi while repository `main` does not yet contain #368. Leave `nexolab-telemetry-service:issue-368-v2` running until #368 is merged and a controlled follow-up deployment path is prepared.

Do not downgrade or restore the production database. Do not delete persistent volumes. No Modbus or other hardware write is authorized.

## Next action

Run fresh exact-head CI on the final #368 branch head containing this checkpoint. If GREEN, perform final 14-file/review/base audit and merge PR #373. Then immediately resume Issue #385 by reconciling PR #390 with post-#368 `main` and renumbering its migration to `20260807_0024` before any further Raspberry Pi user-management acceptance.
