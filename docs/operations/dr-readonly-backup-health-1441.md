# NEXOLAB #1441 — offline read-only backup health

**Source-only. No backup capture, service installation or site activation.**

This command detects missing recovery evidence and a missing or disabled application backup timer.

## Usage

```bash
python3 scripts/nexolab-dr-readonly-health.py
python3 scripts/nexolab-dr-readonly-health.py --inventory /path/to/sanitized-v2.json
```

The optional input is a non-symlink JSON file, mode 0600, at most 512 KiB.
No credentials or private telemetry are permitted.
The existing offline #1433 eight-store contract validates the supplied receipt.

Only the fixed `nexolab-dr-backup.timer` is queried using read-only `systemctl show`.
The probe also checks root filesystem free space. It does not change anything.

## States and checks

The report uses `BLOCKED`, `UNVERIFIED` and `REPORTED_OK` for individual gates.
Its overall status is always `BLOCKED`, with exit code 78 and no site authorization.

- Missing, inactive, disabled or nonpersistent application backup timer.
- Missing, incomplete, duplicate, invalid, stale or future-dated eight-store receipt.
- Less than 20 GiB free on the root filesystem.
- Unverified independent encrypted off-device copy or actual isolated restore.
- Missing real equipment acceptance.

An enabled timer is not evidence that its backup job succeeded.
A recent v2 receipt is an attestation, not independent proof of actual contents.
A PostgreSQL archive list cannot prove complete eight-store recovery.

## Operational boundary

#1428 remains open: the site has only a reported partial PostgreSQL snapshot.
There is no independently verified complete encrypted backup or isolated restore.
The old microSD partition is not an approved backup destination.

Do not activate a schedule, access secret keys, alter Docker or perform Modbus writes.
#1399 site recovery needs separate Product Owner approval and full restore evidence.
A GREEN source-only PR is not a Raspberry update authorization.
