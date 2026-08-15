# Raspberry Pi deployment capacity and evidence retention

The controlled NEXOLAB Raspberry Pi deployment must preserve product data and fail before runtime mutation when the filesystem cannot safely hold deployment evidence, a PostgreSQL backup, and the build working set.

## Safety boundary

Automated capacity cleanup is limited to direct child directories of `runtime/deployments/` whose names exactly match `YYYYMMDDTHHMMSSZ`. The current deployment directory, the newest protected deployments, symlinks, and any deployment containing `.nexolab-preserve` are never removed.

The capacity guard never deletes or truncates:

- `runtime/evidence`;
- edge SQLite data;
- PostgreSQL data;
- MQTT data;
- MinIO/object-storage data;
- Docker named volumes;
- controller/device configuration.

`docker compose down -v`, `docker volume rm`, telemetry deletion, and Modbus/hardware writes are outside this workflow.

## Default retention policy

`scripts/deploy-capacity-guard.sh` applies deterministic limits before a controlled deployment:

- always protect the newest 3 timestamped deployment directories;
- retain at most 12 unmarked timestamped deployments before count pruning applies;
- prune unprotected deployment evidence older than 30 days;
- prune oldest unprotected deployment evidence while timestamped deployment evidence exceeds 3 GiB;
- preserve any directory containing `.nexolab-preserve` regardless of age/count/size pressure.

If protected evidence alone exceeds a limit, it is not deleted. The capacity preflight can fail and require operator review instead.

## Capacity gate

Before pre-deployment inventory, evidence archive creation, PostgreSQL dump, `git fetch/switch/pull`, builds, or container recreation, the deployment calculates a conservative requirement containing:

- minimum free-space reserve: 2 GiB;
- build working-set headroom: 4 GiB;
- metadata/log headroom: 256 MiB;
- `runtime/evidence` archive estimate: 110% of current bytes plus 64 MiB;
- PostgreSQL dump estimate: 110% of `pg_database_size()` plus 64 MiB; if a running PostgreSQL container cannot report its database size, the deployment fails closed before mutation rather than guessing.

The gate is repeated immediately before the large evidence writes. If `free_bytes < required_bytes`, deployment stops before Git/runtime mutation and writes `capacity-preflight.txt` in the current deployment evidence directory. If PostgreSQL size measurement is unavailable, the report records that the required-byte estimate is incomplete and deployment is rejected before mutation.

The report includes free, required, reserve, build, runtime-evidence, PostgreSQL, deployment-evidence and npm-cache byte counts. Docker build cache and npm cache are diagnostic/manual-review categories only; they are not automatically deleted.

## Atomic evidence writes

`runtime-evidence.tar.gz` and `postgresql-pre-upgrade.dump` are first written to hidden `.partial` files. A failed archive/dump removes its partial file. The final evidence filename appears only after a successful write and atomic rename within the same deployment directory.

## Operator recovery from a low-space preflight

1. Read the current `runtime/deployments/<timestamp>/capacity-preflight.txt` and `summary.txt`.
2. Do not delete PostgreSQL, edge SQLite, MQTT, MinIO, `runtime/evidence`, or Docker named volumes.
3. Mark deployment evidence that must be retained for an active acceptance package with:

   ```bash
   touch runtime/deployments/<timestamp>/.nexolab-preserve
   ```

4. Re-run the capacity guard with bounded deployment-evidence pruning if needed:

   ```bash
   cd ~/nexolab-platform
   STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
   AUDIT="$PWD/runtime/deployments/$STAMP"
   mkdir -p "$AUDIT"
   scripts/deploy-capacity-guard.sh \
     --repo "$PWD" \
     --audit-dir "$AUDIT" \
     --report "$AUDIT/capacity-preflight.txt" \
     --prune
   ```

5. If capacity still fails, review the reported npm cache and Docker build cache separately. Cleanup of those caches is an explicit operator action and must not include Docker named volumes.
6. If a running PostgreSQL container cannot report its database size, repair/verify that read-only measurement path before deployment; do not override it with an arbitrary smaller estimate.
7. Re-run `scripts/deploy-current-head-raspberry-pi.sh --runtime-mode lan` only after the capacity gate passes.

## Tunable thresholds

Thresholds can be made more conservative with environment variables; values are bytes unless noted:

- `NEXOLAB_DEPLOY_MIN_FREE_RESERVE_BYTES`;
- `NEXOLAB_DEPLOY_BUILD_HEADROOM_BYTES`;
- `NEXOLAB_DEPLOY_METADATA_HEADROOM_BYTES`;
- `NEXOLAB_DEPLOY_ARCHIVE_ESTIMATE_PERCENT`;
- `NEXOLAB_DEPLOY_ARCHIVE_FIXED_OVERHEAD_BYTES`;
- `NEXOLAB_DEPLOY_POSTGRES_ESTIMATE_PERCENT`;
- `NEXOLAB_DEPLOY_POSTGRES_FIXED_OVERHEAD_BYTES`;
- `NEXOLAB_DEPLOY_EVIDENCE_PROTECTED_COUNT`;
- `NEXOLAB_DEPLOY_EVIDENCE_MAX_COUNT`;
- `NEXOLAB_DEPLOY_EVIDENCE_MAX_AGE_DAYS`;
- `NEXOLAB_DEPLOY_EVIDENCE_MAX_BYTES`.

Invalid/non-numeric settings fail closed rather than silently weakening the capacity policy.
