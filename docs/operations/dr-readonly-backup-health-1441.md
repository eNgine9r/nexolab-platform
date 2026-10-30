# NEXOLAB #1441 — offline read-only backup health

**Source-only. No backup capture, service installation or site activation.**

This read-only command detects missing site recovery evidence and a missing
or inactive application backup timer without accessing production data.

## Usage

```bash
python3 scripts/nexolab-dr-readonly-health.py

python3 scripts/nexolab-dr-readonly-health.py \
  --inventory /path/to/protected-sanitized-v2-inventory.json
```

The optional v2 receipt must be a non-symlink regular JSON file with owner-only
permissions (0600) and at most 512 KiB. It must contain no credentials,
customer data or raw payloads. This command uses the repository's strict
offline #1433 eight-store v2 validator.

The command queries only the exact system timer
`nexolab-dr-backup.timer` using bounded read-only `systemctl show`.
It checks loaded/enabled/active/persistent metadata and obtains root
filesystem free capacity using a read-only disk usage call.

Neither timer presence nor a recent inventory receipt proves that a backup
job actually ran. No service starts, Docker calls, disk writes, networking,
backup uploads, Modbus operations or production changes occur.

## Health states and failure cases

The output contains per-gate statuses `BLOCKED`, `UNVERIFIED`, or
`REPORTED_OK`. Every execution returns global `status: BLOCKED`
and exit 78 until *independent operational evidence* exists outside
this source-only probe.

The report blocks or flags:

- No installed, enabled, active and persistent NEXOLAB application backup timer.
- Missing, malformed, partial or duplicate eight-store v2 inventory evidence.
- Older than 26-hour or future-dated receipt.
- Root filesystem headroom below 20 GiB.
- Unproven separate encrypted off-device custody or fresh-volume restore.
- Unverified real hardware acceptance.

Even an apparently valid v2 receipt remains `UNVERIFIED` as to actual
site data, custody and restore. A one-time `pg_restore --list` on a partial
PostgreSQL archive is never accepted as proof of complete site recovery.

## Operational boundary

The actual #1428 issue remains open. As of the last owner evidence, the
Raspberry has a partial PostgreSQL snapshot but no separately confirmed
off-device encrypted backup or actual eight-store restore. The old microSD
partition is not an approved independent backup destination.

The future operational schedule and protected key custody must be reviewed
and activated separately. Do not use a synthetic DR fixture as real
acceptance. #1399 protected Dashboard/API recovery still requires actual
independent backup evidence and separate Product Owner approval.

**No update signal is granted by this probe.**
