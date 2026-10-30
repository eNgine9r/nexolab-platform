# NEXOLAB #1437 — offline synthetic multi-store recovery harness

**Source-only, synthetic data only. Production backup and site restore NOT performed.**

The existing `nexolab-dr-v1` policy and five-store recovery acceptance stay unchanged.
This additive harness exercises a separate eight-store fixture with authenticated
AES-256-GCM encryption and isolated extraction. It requires no internet.

## Supported commands

```bash
python3 scripts/nexolab-site-dr-fixture-harness.py --check
python3 scripts/nexolab-site-dr-fixture-harness.py --self-test
```

The CLI deliberately accepts **no source path, destination path, key-file path, or site activation flag**.

- `--check` prints source-only status; it does not write any data.
- `--self-test` creates only private OS-managed temporary fixtures, a random
  ephemeral 256-bit key, an encrypted in-memory archive and a new isolated
  fixture restore directory. All fixture material is discarded on exit.
- Neither command calls Docker, PostgreSQL, S3, MQTT, SQLite on site, or hardware.

Eight synthetic asset names match the #1433 v2 inventory categories:
PostgreSQL, VersityGW object storage, central MQTT Dynamic Security, edge
SQLite/outbox, local-auth private/public keys, central ingestion spool, and edge MQTT.

## Fail-closed security evidence

The fixture requires an explicit synthetic-only marker and all eight distinct
assets. Unknown or missing assets, symlinks, invalid data and oversized payloads
are rejected before encryption. The tar contains only regular, allowlisted
files; manifest IDs, formats, sizes, hashes and capture epoch must match.

An AES-256-GCM envelope authenticates the archive with a fixed synthetic-only
additional-authenticated-data context. Wrong-key and tamper tests must fail.
All archive content is authenticated and checked **before** a new sibling
restore target is created. Existing restore targets and paths outside the
private fixture workspace are rejected. The source remains untouched.

A successful result reports `SYNTHETIC_ONLY_PASS`, always accompanied by
`site_backup: NOT_PERFORMED`, `off_device_copy: NOT_PERFORMED`,
`hardware_verified: false` and `site_activation: NOT_AUTHORIZED`.

This small fixture deliberately uses bounded in-memory archives. It is NOT
suitable for site archives, live PostgreSQL dumps, large object trees,
handling production secrets, or production SQLite/WAL continuity.

## Next release blockers

Full #1428 requires a separately reviewed bounded operational capture,
independent protected encrypted off-device storage and key custody, matching
VersityGW migration authority, MQTT and SQLite consistency boundaries and
an actual fresh-volume restore on an isolated host. Reuse the read-only
mapping preflight from #1435 before **any** future site capture.

#1399 Dashboard/API network repair also requires separate Product Owner
approval. No Modbus/hardware write, Docker mutation or site cutover is permitted.
A GREEN source-only merge does not mean `🟢 Оновлюйся`.
