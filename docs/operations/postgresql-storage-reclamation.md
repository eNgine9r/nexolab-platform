# PostgreSQL storage reclamation after 30-day retention (#1551)

Owner runbook. Nothing in this document runs automatically. Every step that removes data or rewrites a table requires the #1428 gate: a verified encrypted backup and an independent restore from it.

## Why two steps

1. **Logical retention** (telemetry service, `RETENTION_TELEMETRY_DELETE_ENABLED=true`) deletes ordinary monitoring samples older than 30 days in short batches. PostgreSQL marks the space as reusable; new telemetry fills it, so the database **stops growing**, but the files on disk do **not** shrink.
2. **Physical reclamation** rewrites `telemetry_samples` and its indexes so the freed space returns to the filesystem. That needs an exclusive table lock and free space for the live rows, so it is a scheduled owner operation, done once after the backlog has drained.

## Baseline (2026-11-23, owner read-only)

| Item                         | Size / value                                                  |
| ---------------------------- | ------------------------------------------------------------- |
| PostgreSQL database          | ~24 GB                                                        |
| `telemetry_samples`          | ~21 GB (2026-11-10: 10.6 M of 13.0 M rows older than 30 days) |
| `telemetry_session_contexts` | ~2.6 GB (session evidence, preserved)                         |
| Free on `/`                  | 23 GiB                                                        |
| Runtime retention            | 365 days, batch 1000 per hour (cannot keep up with ingestion) |

Expected effect, to be confirmed by the dry-run counts in step 1: if roughly 75–85 % of rows are ordinary samples older than 30 days, step 4 returns about **14–18 GB** to the filesystem, and steady-state size stays near 30 days of telemetry (about 4–6 GB) plus preserved session evidence.

## Step 0 — gates (all required before step 2)

- #1428: a fresh encrypted backup of all eight stores, its off-device copy, and an **independent restore** verified from that copy.
- Free space on `/` at least 20 GiB.
- Production healthy: Device Agent `/health` ok, telemetry `/health/ready` ready, ingestion lag normal.

## Step 1 — count (read-only)

With the telemetry service image that contains #1551 (deletion still disabled), set `TELEMETRY_RETENTION_DAYS=30` in the site environment file, then:

```bash
docker compose <site compose arguments> run --rm telemetry-service python -m app.retention --dry-run
```

Record the JSON (`older_than_cutoff`, `eligible`, `preserved_session_evidence`) in #1551. Counting scans the table once and may take several minutes on the Pi.

Sizes for the record:

```bash
docker compose <site compose arguments> exec -T postgres psql -U nexolab -d nexolab -c "
SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) AS total, n_live_tup, n_dead_tup
FROM pg_class JOIN pg_stat_user_tables USING (relname)
WHERE relname IN ('telemetry_samples','telemetry_session_contexts','telemetry_latest');"
```

## Step 2 — enable logical retention (owner decision)

After step 0 and step 1, set `RETENTION_TELEMETRY_DELETE_ENABLED=true` in the site environment file and recreate only the telemetry service through the normal guarded release path. The backlog drains in cycles of at most 60 batches × 2000 rows or 60 seconds, every 5 minutes while a backlog remains. Watch:

- `nexolab_telemetry_retention_backlog_remaining` returns to 0 when the backlog is drained;
- `nexolab_telemetry_retention_deleted_telemetry_total` increases;
- ingestion lag and `/health/ready` stay normal; `retention_failure_total` stays flat.

To pause at any time, set the flag back to `false` and recreate the telemetry service; nothing else changes.

## Step 3 — plain VACUUM (online)

Autovacuum makes the deleted space reusable on its own. After the backlog is drained, an explicit non-blocking run is optional:

```bash
docker compose <site compose arguments> exec -T postgres psql -U nexolab -d nexolab \
  -c "VACUUM (ANALYZE, VERBOSE) telemetry_samples;"
```

It does not lock out writers and does not shrink the files.

## Step 4 — physical reclamation (maintenance window, owner approval)

`VACUUM FULL` rewrites the table and its indexes into new files and then drops the old ones. During the rewrite it holds an `ACCESS EXCLUSIVE` lock on `telemetry_samples`, so ingestion into that table must pause.

Pre-checks (stop if any fails):

```bash
docker compose <site compose arguments> exec -T postgres psql -U nexolab -d nexolab -c "
SELECT pg_size_pretty(pg_total_relation_size('telemetry_samples')) AS current_total,
       (SELECT n_live_tup FROM pg_stat_user_tables WHERE relname='telemetry_samples') AS live_rows,
       (SELECT count(*) FROM pg_stat_activity WHERE state <> 'idle' AND query ILIKE '%telemetry_samples%') AS active_queries;"
df -BG /
```

- Free space must exceed **twice the expected live size** of the table plus 20 GiB reserve (live size ≈ current size × live_rows / (live_rows + deleted rows); with ~5 GB live, at least 30 GiB free is comfortable, 25 GiB is the minimum).
- Retention backlog drained (`retention_backlog_remaining` = 0) and a fresh #1428 backup from **after** step 2.

Procedure:

1. Stop **only** the telemetry service container (PostgreSQL, MQTT and the Device Agent keep running; the Device Agent's local SQLite outbox and MQTT QoS 1 keep new readings until ingestion resumes).
2. Rewrite:

   ```bash
   docker compose <site compose arguments> exec -T postgres psql -U nexolab -d nexolab \
     -c "SET lock_timeout = '30s';" -c "VACUUM (FULL, ANALYZE, VERBOSE) telemetry_samples;"
   ```

3. Start the telemetry service again and confirm `/health/ready` is ready, the ingestion lag returns to normal, the latest readings and sessions show, and `df` reports the gained space.

Expected duration on the Pi: roughly 10–40 minutes for 4–6 GB of live rows. If the rewrite fails or is cancelled, PostgreSQL keeps the original table; restart the telemetry service and investigate. Recovery from data loss is the #1428 restore.

Not used here: `pg_repack` would avoid the exclusive lock but needs an extension in the PostgreSQL image (a separate, reviewed image change); `VACUUM FULL` of the whole database is never needed.

## Afterwards

Steady state needs no further rewrites: the 30-day retention deletes continuously and autovacuum reuses the space. Record before/after `df`, table sizes, `eligible`/`preserved_session_evidence` counts and ingestion continuity in #1551.
