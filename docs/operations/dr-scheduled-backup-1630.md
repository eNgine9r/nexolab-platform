# #1630 DR-A — scheduled encrypted complete backup

Parent: #1428. Order of the DR leaves: **A (#1630) → C (#1631, off-device copy) → B (#1632, isolated restore)**.
This document covers source tooling and the **owner-approved** site procedure. Nothing here is installed,
enabled or executed on the Raspberry Pi without separate explicit approval.

> A successful backup run is **not** recovery evidence. A bundle counts as recoverable only after #1632 restores it
> on an isolated host. Receipts always say `CAPTURED_RESTORE_UNVERIFIED`.

## Components

| File                                                                          | Purpose                                                                                                                       |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `scripts/nexolab-dr-stream.py`                                                | `nexolab-dr-stream-v1` streaming container: AES-256-GCM (STREAM construction), constant memory, `verify` / isolated `extract` |
| `scripts/nexolab-dr-scheduled-backup.py`                                      | Orchestrator: config validation, `flock`, fail-closed capacity, capture of the 8 v2 stores, receipt, Prometheus textfile      |
| `infrastructure/systemd/nexolab-dr-backup.{service,timer}`                    | Hardened low-priority templates (**DO NOT install** without approval)                                                         |
| `infrastructure/systemd/nexolab-dr-backup.example.json`                       | Configuration template; every `CONFIRM-` value must be verified on the site                                                   |
| `infrastructure/observability/prometheus/optional-rules/dr-backup-alerts.yml` | Opt-in local alerts: missing (>26 h), failed run, low headroom                                                                |

Why not `nexolab-backup-bundle.py` (nexolab-dr-v1): it tars and encrypts the whole payload **in memory** from a
**plaintext payload directory**. With a ~19 GB database on a 4 GB Pi, that is impossible and violates
"no unencrypted temporary copies". v1 remains in use for synthetic CI recovery acceptance; the directory snapshots
of v1-stream are tar streams compatible with `scripts/nexolab-volume-archive.py extract`.

## Safety properties (enforced in code and tests)

- **No service interruption.** The only Docker verb is `docker exec` with an allowlist: `pg_dump` (optionally behind
  `nice -n 19`) or `cat <absolute path>`. `pg_dump` tokens must match a strict allowlist — exactly `-Fc`, `-U <ident>`,
  `-d <ident>`, optional `-Z <0-9>`, `-w`/`--no-password`, each at most once — so the dump can only be a custom-format
  archive on stdout from the local server. Everything else is rejected at config load, including `-f`/`--file`, other
  formats, `-h`/`--host`, `-j`, filters, `--clean`/`-c`/`-C`, as well as `stop`, `restart`, `rm`, `kill`, `pause`,
  `run`, interactive or privileged exec and `psql`.
- **No plaintext on disk.** Every byte is encrypted in 1 MiB chunks and written to `.<name>.partial` (0600). SQLite stores
  are captured into memory with the online backup API plus `integrity_check`. They are capped at **192 MiB**: the
  measured RSS growth is ~2.25–2.66× the database size, so the worst case is ~0.5 GiB under `MemoryMax=768M`. Larger
  databases are refused before copying.
- **Verified before it exists.** Cryptographic verification is mandatory: `verify_after_capture=false` is rejected.
  The complete partial file is authenticated and the reserve re-checked **before** the atomic rename. A failure removes
  the partial file, so an unverified `.nxs` never appears.
- **Capacity fail-closed.** The run refuses to start unless `free − max_backup_bytes ≥ reserve`, where the reserve is
  ≥ 20 GiB and cannot be configured lower. While writing, the bundle cap is exact (ciphertext bytes, no tolerance) and
  the reserve is checked every 16 MiB and once more before finalization. Per-store caps are enforced while streaming.
- **Extract never leaves secrets behind.** If `extract` fails, the destination it created is removed completely,
  including any partially decrypted files.
- **One run at a time.** An overlapping start exits `75` (`SuccessExitStatus`) and sets `nexolab_dr_backup_overlap_skipped`.
- **No deletion.** On failure, only the run's own partial file is removed. There is no automatic retention or pruning
  in this Work Package; capacity alerts and the fail-closed preflight protect the disk instead.
- **Low priority.** `Nice=19`, idle CPU/IO scheduling, `CPUQuota=60%`, `MemoryMax=768M`. `pg_dump` runs inside the
  PostgreSQL container under `nice -n 19`.

## Consistency per store

| Store                                                              | Method                                             | Boundary                                                                                                                                                                                                              |
| ------------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `postgresql`                                                       | `docker exec … pg_dump -Fc -Z 3`                   | Logical snapshot (single transaction, MVCC); acquisition continues                                                                                                                                                    |
| `edge-sqlite-outbox`, `central-ingestion-spool`                    | `sqlite_online` (host read-only open + backup API) | Transactionally consistent; uncommitted writes excluded (tested)                                                                                                                                                      |
| `object-storage`, `mqtt-dynamic-security`, `edge-mqtt-persistence` | `directory_snapshot`                               | **Verified unchanged during capture**: a full metadata signature before and after; any change fails the run (retried next schedule). This is _not_ the "separately approved quiesce" of #1439 — no service is stopped |
| `local-auth-*-key`                                                 | `docker exec … cat` or `file_snapshot`             | Atomic read of an operator secret                                                                                                                                                                                     |

`central-ingestion-spool` and `edge-mqtt-persistence` are rebuildable. They may be set to
`"disposition": "rebuildable_excluded"`, but only with an explicit reason.

### Cross-store consistency: PostgreSQL ↔ object storage (review P1-3)

The risk: `equipment_images.storage_key` references objects. If objects were captured **before** the database, an image
uploaded in between would be referenced by the dump but missing from the object copy.

How the application behaves (`services/telemetry-service/app/refrigeration/api.py`):

- the upload writes the object **first** and commits the referencing row afterwards;
- an object is deleted only as compensation when that row insert fails;
- keys are unique UUIDs and are never overwritten;
- there is no endpoint that deletes committed images.

The solution implemented here:

1. **Capture order:** keys, MQTT, SQLite stores, then `postgresql`, then **`object-storage` last**. Every object
   referenced by the pg_dump snapshot therefore already exists when the object tree is captured. Orphan objects from
   in-flight uploads are harmless.
2. **Deletion guard:** the object paths are recorded just before `pg_dump` starts, i.e. before its snapshot point. If any
   of them is missing when the object tree is captured, the run fails (`deleted after the database snapshot`) and
   keeps no bundle.
3. **Honest status:** the receipt records `cross_store_consistency.postgresql_object_storage.status =
ORDERED_NO_DELETIONS_RESTORE_REFERENCE_CHECK_UNVERIFIED`.

Residual risk: a future code path that deletes committed objects during the dump window would not be fully covered.
**Site acceptance of #1630 is therefore BLOCKED** until #1632 verifies, on an isolated restore, that every
`equipment_images.storage_key` resolves to an object with the recorded `checksum_sha256`.

## Bundle format `nexolab-dr-stream-v1`

`MAGIC "NEXOLAB-DRS-1\n"`, then `u32 header length`, then the canonical JSON header (format, `aes-256-gcm-stream`,
chunk size, 7-byte nonce prefix, key fingerprint, repository, commit, created_at). It is followed by chunks
`u32 len ‖ AES-GCM(ciphertext ‖ tag)`, with nonce = prefix ‖ counter(4) ‖ final flag(1) and the header as AAD.
The decrypted plaintext is framed as BEGIN(json) DATA* END(path, size, sha256) … MANIFEST, then END_OF_STREAM.

`verify` rejects all of the following: a wrong key (fingerprint), reordered, replayed or bit-flipped chunks, header
tampering, truncation before the final chunk, trailing bytes, unsafe or duplicate paths, and per-entry hash or
manifest mismatch.

## Owner-approved site procedure (NOT yet authorized)

All of the following steps are **read-only** until step 5.

1. **Confirm sources (read-only):**
   ```sh
   docker ps --format '{{.Names}}'
   docker volume ls --format '{{.Name}}' | grep -E 'object-storage|mqtt|device-agent|spool'
   docker volume inspect -f '{{.Mountpoint}}' <volume>
   docker exec nexolab-central-postgres-1 sh -c 'echo $POSTGRES_USER $POSTGRES_DB; which nice pg_dump'
   ```
   Replace every `CONFIRM-` value in the example. Then confirm that the host `python3` has
   `cryptography` (`python3 -c 'import cryptography'`).
2. **Key and custody (#1631):** generate exactly 32 random bytes as `/etc/nexolab/dr-backup.key`, root:root `0600`.
   Store an independent copy of the key **separately from every bundle**. Losing the key makes all bundles worthless.
   Record only the fingerprint, which is printed in every receipt.
3. **Install the config** as `/etc/nexolab/dr-backup.json` (root:root `0600`) and create `/var/backups/nexolab/dr` (`0700`).
4. **Dry plan:** `python3 -I -B scripts/nexolab-dr-scheduled-backup.py --config /etc/nexolab/dr-backup.json --plan`.
   It reads no data and writes nothing; it fails with exit 78 if capacity is insufficient.
5. **First manual run, in an approved window.** Record the Device Agent queue, `/health/ready` ingestion lag and
   container `StartedAt`/`RestartCount` before, during and after the run. Then run
   `scripts/nexolab-dr-stream.py verify --stream <bundle> --key-file /etc/nexolab/dr-backup.key`.
6. **Timer (separate approval):** copy the units to `/etc/systemd/system/`, run `systemctl daemon-reload`, then
   `systemctl enable --now nexolab-dr-backup.timer`. Confirm with `scripts/nexolab-dr-readonly-health.py`
   (`scheduler`: REPORTED_OK).
7. **Alerts (separate approval):** move `dr-backup-alerts.yml` from `optional-rules/` into the loaded rules once
   the textfile metric exists.

## Rollback

```sh
systemctl disable --now nexolab-dr-backup.timer
rm /etc/systemd/system/nexolab-dr-backup.service /etc/systemd/system/nexolab-dr-backup.timer
systemctl daemon-reload
```

Bundles, receipts, the key and production data are **not** touched by the rollback. Remove the optional alert rule
if it was enabled.

## Verification and restore pointers

- Integrity only: `nexolab-dr-stream.py verify` (no plaintext written).
- Isolated restore (#1632 only, never on the production Pi): `nexolab-dr-stream.py extract --output-dir <new empty dir>`,
  then `pg_restore` into a fresh PostgreSQL and `nexolab-volume-archive.py extract` for directory snapshots, then
  `scripts/verify-restored-platform.sh`.

## Evidence status (this Work Package)

| Item                                                                                                                                                                                   | Status                                          |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| Unit, integration and negative tests (synthetic)                                                                                                                                       | CI                                              |
| Local **dev** integration: real `pg_dump` from a dev PostgreSQL → bundle → `pg_restore` into an isolated temporary PostgreSQL, identical row counts in 44 tables, containers unchanged | Recorded in PR                                  |
| Site timer installed / real production backup / disruption measurement on the Pi                                                                                                       | **NOT PERFORMED — owner approval required**     |
| Off-device copy (#1631), isolated restore (#1632)                                                                                                                                      | **UNVERIFIED**                                  |
| PostgreSQL ↔ object-storage reference integrity on restore (`storage_key` → object + checksum)                                                                                         | **UNVERIFIED — blocks site acceptance (#1632)** |
