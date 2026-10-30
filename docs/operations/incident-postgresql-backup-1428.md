# NEXOLAB P0 — bounded PostgreSQL incident snapshot (#1428)

This is an emergency **partial** backup for the October 29 Docker-network outage.
It does not restore the Dashboard or replace complete offline disaster recovery.

## Actual Pi facts (2026-10-30)

- Accepted installed packaged source: `ffdefc4550d71e211724de1154ffe9057f905c9c`.
- PostgreSQL remains running and queryable, reported database size 19 GB.
- Root SSD has approximately 29 GB free of 234 GB.
- Most recent observed `/var/backups/nexolab` files date to October 14.
- No scheduled complete NEXOLAB application backup was found in the inspected
  system or user systemd timer listings.
- Dashboard, Telemetry API and VersityGW Docker networks/host ports are absent.
- RS-485 adapters are intentionally unplugged and are not a login recovery prerequisite.

## Prepare and preflight (no site mutation)

The script is reviewed source-only. It is **not** installed on Pi by the
repository PR. Transfer an exact verified source revision to the Pi; never
execute an arbitrary online `curl | bash`, source checkout drift, or a downloaded
script without verifying its SHA-256.

The script accepts only `--check` (read-only preflight) or no arguments (backup):

```bash
sudo bash scripts/nexolab-safe-pg-incident-backup.sh --check
```

It rejects non-root invocation, unsafe backup directory ownership/write
permissions, missing or replaced NEXOLAB PostgreSQL container, failed capacity
check, and a backup directory on a different filesystem from the protected root.

## Create bounded copy after source verification

```bash
sudo bash scripts/nexolab-safe-pg-incident-backup.sh
```

The read-only PostgreSQL client uses bounded CPU/memory/time, `pg_dump -Fc -Z 3`,
a host-side 4 GiB maximum archive stream and a 20 GiB remaining-disk reserve.
A failed or truncated stream cannot be promoted to a final `.dump` filename.
The compressed archive stays mode 0600 inside root-owned
`/var/backups/nexolab`; the pre-existing archives are not modified.
No Docker restart, Compose operation, volume removal or controller write occurs.

On success, the script prints `PG_BACKUP_ARCHIVE=CREATED`,
`PG_RESTORE_TOC=PASS`, `PG_RESTORE_ACTUAL=NOT_PERFORMED`, byte length and SHA.
If it blocks, **do not bypass capacity limits**, prune data or reduce the reserve.

## Important non-acceptance boundary

`pg_restore --list` verifies the archive table of contents, **not**
actual recovery. A single PostgreSQL dump does not include:
private VersityGW S3 objects, central MQTT persistence and Dynamic Security,
edge SQLite/outbox, local-auth private signing keys, or concurrent cross-store
consistency. It must not authorize a protected site network/port cutover.

Before live Docker repair: make a recent complete encrypted backup with
independent off-device copy, verify recovery to isolated NEW volumes, confirm
exact Compose/image/volume and port ownership, check physical LAN vs Docker
CIDR overlap and preserve a tested rollback. Never publish backup data/keys
in GitHub Issues, PRs, chat transcripts, or CI artifacts.

Relevant incidents: #1399 (network recovery), #1393 (Dashboard :3000),
#1409 (IPAM overlap), #1426 (isolated PC), #1428 (complete offline backup).
