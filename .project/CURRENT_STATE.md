# NEXOLAB Current State

Updated: 2026-08-11

Verified repository baseline on `main`: `d75b353435e8c613203017cb68ee68c1f63d3268`.

Active Work Package: Issue #368 / PR #373 — final exact-head verification after successful Raspberry Pi physical acceptance and merged telemetry image security remediation.

## Issue #396 — completed security dependency

Issue #396 / PR #397 removed the fresh telemetry-image HIGH findings caused by vulnerable libraries vendored inside runtime `pip`.

Final head `92be9b3364aedd01e6e830e4711c358a041f9781` completed 13/13 workflows GREEN. Telemetry Container Supply Chain passed exact image build, SBOM, Trivy policy, release-manifest and secret checks. Offline Bundle passed disconnected startup and update/rollback persistent-data preservation. No new vulnerability exception was added.

PR #397 squash-merged as `d75b353435e8c613203017cb68ee68c1f63d3268`.

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

## Final repository reconciliation

After #396 merged, PR #373 was reconciled again through two-parent commit `97917fe627c704f7aa7fd6d32c7cfb0c459d1256` using current `main=d75b353435e8c613203017cb68ee68c1f63d3268` as the base tree.

The reconciliation preserves the ten physically verified #368 telemetry implementation/test blobs byte-for-byte and inherits the hardened telemetry Dockerfile/requirements/security tests from merged #396.

This checkpoint changes only the four `.project` source-of-truth files. A fresh exact-head CI run is mandatory before Ready/merge.

## Alembic ordering hazard with Issue #385

Issue #385 / PR #390 is software verified at `8bb31364a7523164fab95c29aef9d8a839283213`, but its unmerged migration also uses revision `20260807_0023` based on `20260805_0022`.

The controlled production Raspberry Pi database records `20260807_0023` as the #368 telemetry projection migration. Merging #385 first would assign different schema meaning to the same revision id and could cause Alembic to skip the #385 permission migration on that database.

Safe ordering remains:

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

Run fresh exact-head CI on the final #368 branch head containing this checkpoint. If GREEN, perform final focused-diff/review/base audit and merge PR #373. Then immediately resume Issue #385 by reconciling PR #390 with post-#368 `main` and renumbering its migration to `20260807_0024` before any further Raspberry Pi user-management acceptance.
