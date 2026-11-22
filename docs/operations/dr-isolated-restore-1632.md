# #1632 DR-B — isolated restore and verification receipt

Parent: #1428. Order of the DR leaves: **A (#1630, backup) → C (#1631, off-device copy) → B (#1632, this document)**.

> **What this work package delivers:** source tooling, unit tests and a local rehearsal on a development machine
> with synthetic data. **It does NOT produce the site proof.** The real proof (restore of the leaf-C media on an
> isolated host with the internet disconnected) has not been performed and needs the owner. A receipt from
> `mode=rehearsal` says so in its `statement` and can never set `isolated_restore_verified`.

## Components

| File                                                           | Purpose                                                                                                                                      |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `scripts/nexolab-dr-isolated-restore.py`                       | Isolation preflight, custody re-verification, isolated extract, restore of all eight stores into fresh volumes, offline start, receipt       |
| `scripts/nexolab-dr-isolated-restore-rehearsal.py`             | Opt-in local end-to-end rehearsal (Docker): synthetic production → unmodified leaf A → leaf C `copy_bundle` → restore → teardown             |
| `tests/test_ci_dr_isolated_restore.py`                         | Deterministic tests without Docker (refusals, custody binding, plaintext cleanup, diff detection, RPO/RTO, receipt hash, v2 field alignment) |
| `tests/test_ci_dr_object_metadata_xattrs.py`                   | `user.*` xattr capture/extract round trip, allowlist, caps, unsupported file system, pre-fix archives, metadata fidelity evaluation          |
| `scripts/nexolab-dr-stream.py`, `nexolab-dr-offdevice-copy.py` | Reused unchanged: `verify`/isolated `extract`, the shared custody receipt validator                                                          |
| `scripts/nexolab-volume-archive.py`                            | Directory snapshot extract, including the object metadata (`user.*` extended attributes, see the leaf-A doc)                                 |

No Compose file is used: the tool drives `docker` directly so that every resource is created with
`--internal`, `--pull never`, no published ports and an `nx-dr-` name plus a run label.

## What the restore does

1. **Isolation preflight (refuses with exit 78, before anything is decrypted):**
   - any `NEXOLAB_*`, `DATABASE_URL`, `PG*` connection, `MQTT_HOST`/`MQTT_PORT`, object-storage endpoint,
     `DOCKER_HOST` or `DOCKER_CONTEXT` variable in the environment;
   - any connection string, URL or endpoint anywhere in the configuration (`*url`, `*dsn`, `*endpoint`, `scheme://`);
   - `nexolab-edge-01` (always) and every configured production name **resolves**, or any of their addresses
     answers on TCP 22/1883/3000/5432/8082/8883/9000;
   - in `mode=site`: the internet is reachable (offline proof), production-named Docker resources
     (`nexolab-central-*`, `nexolab-edge-*`) exist on the target, an image is neither digest-pinned nor listed in
     `approved_image_ids`, or the bundle is on the same file system as the restore work directory;
   - the planned network/volumes/containers already exist (restore targets must be fresh).
   - It records `restore_target_identity_sha256` (hash of host name, machine-id, Docker engine id, architecture,
     kernel) and refuses if it equals the custody `destination_identity_sha256`.
2. **Custody (exit 78 on any mismatch):** the custody receipt is validated by the shared leaf-C validator
   (`validate_custody_receipt` in `nexolab-dr-offdevice-copy.py`). The bundle **on the media** must have the
   receipt's name, size and SHA-256; `sha256(key file bytes)` must equal `key_fingerprint_sha256`. Then the whole
   stream is authenticated (`nexolab-dr-stream.py` reader) and `source_manifest_sha256` must equal
   `sha256(canonical_json(decrypted in-stream manifest))`. The manifest must classify all eight stores exactly once,
   and every stream entry must match it. The leaf-A receipt normally stays on the (lost) Pi, so it is **optional**;
   when supplied (`media.backup_receipt`) it must agree with the stream.
3. **Isolated extract:** `extract_file` into `<work_dir>/plaintext` (new, `0700`). This directory is removed on
   success **and** on failure. The receipt records `plaintext.removed` (or `plaintext_removed_after_failure`).
   Runtime secrets (random passwords, env files) are removed as well. Directory snapshots are extracted into the
   fresh volumes together with their `user.*` extended attributes (object metadata). In `mode=site` an extract onto
   a volume that cannot store them **fails the restore**. In `mode=rehearsal` the loss is allowed but reported as a
   `DEGRADED:` warning and in `stores.object-storage.verification.xattrs.dropped`.
4. **Restore into fresh volumes** on a new `docker network create --internal` network:

   | Store                     | Restore                                                                                             | Verification                                                                                                                                                                                                                                                                       |
   | ------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
   | `postgresql`              | fresh PostgreSQL, `pg_restore --exit-on-error --no-owner --no-privileges` from stdin                | exact per-table row counts against the archive's own data (`pg_restore --data-only` COPY rows), latest `captured_at` per channel against the archive, Alembic head                                                                                                                 |
   | `object-storage`          | `nexolab-volume-archive.py extract` into a fresh volume, VersityGW `posix /data` with new root keys | tree (path, size, SHA-256) equals the archive; every `equipment_images.storage_key` exists with its `checksum_sha256`; bucket still private; HEAD per object (ETag/Content-Type against the database and the source observation); `object-storage-s3.py stat-keys`; API image read |
   | `mqtt-dynamic-security`   | extract into a fresh volume, start the release Mosquitto Dynamic Security image                     | tree equals archive; clients/roles/ACLs present (counts and a hash of usernames); broker running                                                                                                                                                                                   |
   | `edge-mqtt-persistence`   | extract into a fresh volume (not started: the edge broker is not part of the central stack)         | tree equals archive                                                                                                                                                                                                                                                                |
   | `edge-sqlite-outbox`      | file into a fresh volume (Device Agent not started: no hardware)                                    | `integrity_check`, table counts, SHA-256 equals manifest                                                                                                                                                                                                                           |
   | `central-ingestion-spool` | `spool.db` into a fresh volume mounted into the restored telemetry service                          | `integrity_check`, table counts, SHA-256 equals manifest                                                                                                                                                                                                                           |
   | `local-auth-*-key`        | `private.pem` (`0400`) / `public.pem` (`0444`, uid 10001) into a fresh volume                       | private key derives the public key; login works and the issued RS256 token verifies with the **restored** public key                                                                                                                                                               |

5. **Migrations-to-ready:** `alembic upgrade head` with the supplied telemetry image (input, ideally a digest from
   the offline package), then `alembic heads` must equal `alembic_version`. Row-count changes caused by migrations
   are reported separately.
6. **Offline start:** telemetry service with `MQTT_ENABLED=false` (no broker passwords are in the bundle; ingestion
   must not run on a restore), `RETENTION_ENABLED=false` (retention would delete restored history),
   `BROKER_CONTROL_ENABLED=false`, local auth with the restored keys, object storage pointing at the restored
   gateway. The tool waits for `/health/ready` with `database=ready` from inside the container.
7. **Application checks (all from inside the internal network):** egress probe (internet and production
   addresses unreachable from the stack), local login + `/api/v1/auth/session`, saved dashboard `GET` and
   `telemetry.csv` for the observed window, equipment image content through the API.
8. **Receipt:** `nexolab-dr-isolated-restore-receipt.json` with a `.sha256` sidecar and
   `inventory-v2-restore-fields.json` (storage block + per-asset `RESTORE_FIELDS` of
   `validate-site-dr-inventory-v2.py`). Status is `PASS` only when every mandatory check passed in `mode=site`;
   `REHEARSAL_PASS` / `REHEARSAL_PASS_WITH_WAIVERS` otherwise; `FAIL` on any failed check. Acceptance is never
   derived from `pg_restore --list`.

### RPO and RTO

- **RTO** = from the start of custody verification to the first `/health/ready` with `database=ready`.
- **RPO** = backup age when the restored stack became ready (`ready_at − created_at` of the stream manifest; the
  capture start, so conservative). `newest_restored_sample_age_seconds` is reported as well.
- Gaps are computed against `objectives` in `security/disaster-recovery-assets.json`
  (`software_rpo_seconds: 0`, `software_restore_target_seconds: 600`). Those objectives describe the quiesced CI
  drill. A daily scheduled backup has an RPO of up to 24 h plus the capture time, so **the RPO objective will be
  missed by design**. The owner must either accept the gap or change the objective. The receipt never hides it.

### Source observation (comparison with production)

The restore compares against the archive by construction. To compare with **production**, the owner records a
read-only observation right after the backup and passes it as `verification.source_observation`:

```sh
# On the Pi, read-only, right after the leaf-A run:
python3 scripts/nexolab-dr-isolated-restore.py observe-sql > /tmp/observe.sql
docker exec -i nexolab-central-postgres-1 psql -X -q -At -U nexolab -d nexolab < /tmp/observe.sql > observation-db.json
# Saved Dashboard rendering of a window that ENDS BEFORE the backup (owner session token, read-only GET):
curl -fsS -H "Authorization: Bearer $TOKEN" -H "X-Organization-ID: $ORG" \
  "http://127.0.0.1:8082/api/v1/live-dashboards/$DASHBOARD/telemetry.csv?from=$FROM&to=$TO&timezone=UTC" | sha256sum
curl -fsS -H "Authorization: Bearer $TOKEN" -H "X-Organization-ID: $ORG" \
  "http://127.0.0.1:8082/api/v1/live-dashboards/$DASHBOARD" | python3 -c \
  'import sys,json,hashlib;d=json.load(sys.stdin);print(hashlib.sha256(json.dumps(d.get("view_settings"),sort_keys=True,separators=(",",":")).encode()).hexdigest())'
```

Object metadata on the production gateway: one read-only `HEAD` per referenced object, using the existing helper
with the object-storage credentials and endpoint the stack already uses:

```sh
docker exec nexolab-central-postgres-1 psql -X -At -U nexolab -d nexolab \
  -c "SELECT storage_key FROM equipment_images ORDER BY 1" > /tmp/object-keys.txt
python3 scripts/object-storage-s3.py stat-keys --bucket nexolab-equipment-images --keys-file /tmp/object-keys.txt \
  > /tmp/objects.jsonl      # one {"key","etag","content_type",...} per line; these become "objects"
```

Combine these into a JSON file:
`{"schema_version":1,"kind":"nexolab-dr-source-observation","observed_at":"…Z","table_counts":{…},"latest_captured_at":{…},"dashboards":[{"id":"…","from":"…Z","to":"…Z","timezone":"UTC","csv_sha256":"…","view_settings_sha256":"…"}],"objects":[{"key":"…","etag":"\"…\"","content_type":"image/png"}]}`.
The schema treats `objects` as optional, but without it object metadata fidelity cannot be `OK` (see below).
Restored counts lower than the observation are reported as "explained by the consistency boundary" (data written
after the snapshot). Higher counts, or a different latest sample older than the backup point, fail. The dashboard
CSV and view settings must be byte-identical.

### Object metadata fidelity

The receipt reports `object_storage_s3.metadata_fidelity` (counts only, no keys or values), and the
`object_storage.metadata_fidelity` check is based on it:

| Value                              | Meaning                                                                                                                                                   |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OK`                               | every `equipment_images` object answers `HEAD` with the ETag and Content-Type recorded in the database **and** observed on the source gateway (`objects`) |
| `DEGRADED`                         | an object is missing, or its ETag or Content-Type is missing or different (check fails, status `FAIL`)                                                    |
| `UNVERIFIED_NO_SOURCE_OBSERVATION` | the database values match, but the observation has no `objects` list (check fails; never `OK`)                                                            |

`object_storage.stat_keys` also runs `object-storage-s3.py stat-keys` against the restored gateway. It fails when an
object has no ETag. The receipt keeps `schema_version: 1`: the new fields are additive, and the value `PRESERVED`
(never reached before this fix) is replaced by `OK`. Before the fix, DEGRADED was only a warning. It is now a failed
check, because a restore without object metadata is not faithful.

## Owner-run procedure on the isolated host (NOT executed by this work package)

### Choose the host (owner decision)

| Option                         | Fidelity                                                                                                                              | Notes                                                                                                                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Spare Raspberry Pi (arm64)** | Best: same architecture and images as edge-01                                                                                         | Preferred. Fresh OS, Docker, nothing from edge-01 (no `/etc/nexolab`, no Tailscale identity of edge-01, not joined to the site Wi-Fi/LAN during the proof)                                      |
| PC with Docker (amd64)         | Medium: arm64 images run only under emulation (`binfmt`/QEMU), or amd64 images rebuilt from the same commit (approved, not identical) | Check each image first: `docker image inspect -f '{{.Architecture}}' <image>`. The receipt warns when an image architecture differs from the engine. arm64-only defects can be hidden on amd64. |
| VM                             | Like the PC option                                                                                                                    | Use a NAT-less host-only network or no network adapter at all for the proof                                                                                                                     |

Multi-arch availability (source in this repository): the telemetry and Mosquitto images build from multi-arch
bases (`python:3.13-slim-trixie`, `eclipse-mosquitto`), `infrastructure/object-storage/Dockerfile` builds
`amd64` and `arm64` explicitly, `postgres:16-alpine` is multi-arch. **The offline package ships the architecture
it was built for**; for a PC, either load the arm64 archives and enable emulation or obtain amd64 archives built
from the same release commit and list their image ids in `approved_image_ids`.

### What must be physically present

1. The isolated host, with Docker and Python 3 + `cryptography`, and a checkout of this repository at the release
   commit (scripts only; no production data).
2. The **leaf-C media** (USB SSD) with the bundle and its `<stem>.custody-receipt.json`, mounted read-only.
3. The **backup key** from the second custodian location (key-only USB stick or paper escrow typed into a
   `0600` file on the target), never on the backup SSD.
4. The **release images** from the offline package (`docker load`), referenced by digest.
5. The password of one local account (owner knowledge or protected custody) in a `0600` file.
6. The source observation file from the backup day (optional for a smoke test, required in `mode=site`).

### Disconnect the internet (offline proof)

- Spare Pi / PC: unplug the Ethernet cable and disable Wi-Fi (`nmcli radio wifi off`) and Tailscale
  (`sudo tailscale down`), or physically remove the uplink from the switch the host is on.
- Confirm: `ping -c1 -W2 1.1.1.1` fails, `getent hosts nexolab-edge-01` returns nothing.
- The tool proves it again in its preflight (`isolation.internet_disconnected`, `isolation.production_unreachable`)
  and from inside the restored stack (`isolation.container_egress_blocked`).

### Commands

```sh
sudo mkdir -p /media/nexolab-dr && sudo mount -o ro /dev/sdX1 /media/nexolab-dr        # leaf-C media, read-only
sudo mkdir -p /media/key && sudo mount -o ro /dev/sdY1 /media/key                     # key escrow stick, read-only
for f in /path/to/offline-package/images/*.tar; do docker load -i "$f"; done
docker image inspect -f '{{.RepoDigests}} {{.Architecture}}' <each image>             # record in the evidence

cat > /var/tmp/nx-dr-restore.json <<'JSON'
{
  "schema_version": 1, "kind": "nexolab-dr-isolated-restore", "mode": "site",
  "media": {
    "bundle": "/media/nexolab-dr/nexolab-dr-YYYYMMDDTHHMMSSZ-xxxxxx.nxs",
    "custody_receipt": "/media/nexolab-dr/nexolab-dr-YYYYMMDDTHHMMSSZ-xxxxxx.custody-receipt.json"
  },
  "key_file": "/media/key/nexolab-dr-backup.key",
  "work_dir": "/var/lib/nx-dr-restore/run-1", "evidence_dir": "/var/lib/nx-dr-restore/evidence-1",
  "resource_prefix": "nx-dr-site-restore-1",
  "images": {"telemetry": "…@sha256:…", "postgres": "postgres@sha256:…",
             "object_storage": "…@sha256:…", "mqtt": "…@sha256:…"},
  "production_hosts": ["nexolab-edge-01", "<edge-01 LAN IP>", "<edge-01 Tailscale IP>"],
  "require_internet_disconnected": true,
  "local_auth": {"username": "<local admin>", "password_file": "/var/tmp/nx-dr-password",
                 "organization_id": "<organization UUID>"},
  "verification": {"source_observation": "/media/nexolab-dr/observation-YYYYMMDD.json"}
}
JSON
python3 -I -B scripts/nexolab-dr-isolated-restore.py preflight --config /var/tmp/nx-dr-restore.json
python3 -I -B scripts/nexolab-dr-isolated-restore.py restore --config /var/tmp/nx-dr-restore.json
python3 -I -B scripts/nexolab-dr-isolated-restore.py verify-receipt \
  --receipt /var/lib/nx-dr-restore/evidence-1/nexolab-dr-isolated-restore-receipt.json
# Inspect the restored stack if needed (no ports are published; use docker exec), then:
python3 -I -B scripts/nexolab-dr-isolated-restore.py teardown --prefix nx-dr-site-restore-1
```

Record RPO/RTO from `rpo_rto` in the receipt. Also write down the wall-clock time from "media plugged in" to
"ready", because the tool's RTO starts at custody verification and does not include unpacking images or wiring.

### Evidence to attach to #1632 / #1428

- `nexolab-dr-isolated-restore-receipt.json`, its `.sha256` sidecar and `inventory-v2-restore-fields.json`
  (contain hashes, counts and statuses only; no secrets).
- The output of `verify-receipt`, the preflight output, `docker image inspect` digests/architectures.
- A photo or note of the physical setup: host model, unplugged uplink, media label (no key material).
- `restore_target_identity_sha256 != destination_identity_sha256` (both in the receipt).
- Then run `nexolab-dr-readonly-health.py --restore-receipt <receipt> --custody-receipt <custody receipt>`
  (optionally with `--offdevice-destination <media>`). Its `isolated_restore` gate (Product Owner request) becomes
  `REPORTED_OK` only for an intact, site-mode, all-PASS, waiver-free, warning-free receipt with
  `metadata_fidelity` `PRESERVED`, bound to the custody receipt (and the newest copy on the media), with
  `restore_target_identity_sha256 != destination_identity_sha256` and not older than 35 days. Anything else is
  `BLOCKED` with the reason; without the options the gate stays `UNVERIFIED`. RPO/RTO gaps are echoed as findings,
  not blockers. `REPORTED_OK` is receipt-attested and re-verified locally, not an independent proof of the physical
  restore and not site readiness. Rules: `docs/operations/dr-readonly-backup-health-1441.md`.

## Local rehearsal (development machine, synthetic data)

```sh
docker build -t nx-dr/telemetry:rehearsal services/telemetry-service
docker build -t nx-dr/object-storage:rehearsal infrastructure/object-storage
docker build -t nx-dr/mqtt:rehearsal infrastructure/mqtt/dynamic-security
python scripts/nexolab-dr-isolated-restore-rehearsal.py --workspace <new empty dir>
```

It builds a synthetic production (PostgreSQL 16 at Alembic head, 5,760 telemetry samples on 4 channels, a Saved
Dashboard with `view_settings`, a local account and RS256 keys, an equipment image uploaded through the API into
VersityGW, Mosquitto Dynamic Security with ingestion and node clients, SQLite outbox/spool, edge MQTT files). It
then runs the **unmodified** leaf-A orchestrator in a Linux container, runs leaf C's `copy_bundle` to a second
directory (only the device-identity probe is simulated because a PC has one disk), runs two negative restores
(tampered custody hash, wrong key) and the restore, and removes every `nx-dr-` resource it created. The source
observation includes the source gateway's `HEAD` results (`objects`). After a successful restore, a second, labelled
VersityGW on the restored object volume answers `HEAD` and `stat-keys`. The rehearsal fails unless ETag and
Content-Type equal the source (`metadata_equal_source` in `rehearsal-summary.json`).

The PR records the rehearsal output. The rehearsal machine can reach the real edge-01 over Tailscale and has
internet access, so the restore runs with the explicit rehearsal waiver `isolation.production_unreachable`. The
status says `REHEARSAL_PASS_WITH_WAIVERS`, and the restored stack itself is still proven unable to reach either
(container egress check).

## Known gaps and findings

- **Resolved: VersityGW object metadata was not preserved by leaf A.** The posix backend keeps ETag/Content-Type in
  `user.*` extended attributes, which the original `directory_snapshot` did not capture. After a restore, `HEAD`
  returned no ETag or Content-Type and `object-storage-s3.py stat-keys` failed (`KeyError: 'ETag'`). Leaf A now
  captures the attributes as `SCHILY.xattr.*` PAX records and the restore re-applies them (details in
  [`dr-scheduled-backup-1630.md`](dr-scheduled-backup-1630.md#object-metadata-extended-attributes)).
  **Bundles taken before the fix still lack the metadata.** Restoring one reports `scheme: none` for the object
  archive, `metadata_fidelity: DEGRADED`, a failed `object_storage.metadata_fidelity` check and a warning. After
  installing the fix, the owner should take a fresh backup and off-device copy, and use that bundle for the site proof.
- The restore volumes must support `user.*` extended attributes (ext4 or xfs on the target; Docker named volumes on
  those file systems do). `mode=site` stops the restore on a volume that cannot store them.
- `scripts/verify-restored-platform.sh` and `disaster-recovery-domain-counts.sql` are bound to the synthetic CI
  fixture (organization `…0099`, fixed event ids, exactly 3 telemetry rows) and **cannot** be run against a real
  restore. This tool reuses the domain → table mapping of the SQL and compares full tables instead.
- MQTT ingestion is not started on the restore (no broker passwords in the bundle, and ingestion must not run).
  Dynamic Security is verified from the restored file and the broker start. A login with the admin account needs
  the admin password from custody (not automated).
- The Device Agent and the edge broker are not started (hardware/edge only). Their stores are restored and verified.
- The Dashboard frontend is not started. The API rendering of the saved dashboard is verified instead.
