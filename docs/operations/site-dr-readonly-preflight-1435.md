# NEXOLAB #1435 — bounded read-only site DR capture preflight

Status: **source-only**. This is a deterministic observation/consistency gate for the existing LOCAL_LAN deployment. It is neither a backup runner nor permission to repair the Docker network, restore production data, stop acquisition or deploy a build.

The v2 DR inventory contract from #1433 still requires **actual independently verified** encrypted off-device custody and isolated fresh-volume restore receipts. This preflight **never** creates or validates such receipts.

## Execution contract

Run only from the accepted installed repository, after reviewing the exact committed source and trusted on-site backup destination. It requires a prepared **root-owned, mode-0700 directory** at `/var/backups/nexolab`; it does not create paths, follow leaf symlinks, chmod, chown or write any output file. The destination must already be mounted on a filesystem distinct from the live root, itself root-owned mode 0700, and have at least 16 GiB available. Filesystem independence alone **does not prove independent physical media or an off-device copy**.

Example syntax (do not run with a guessed mount or authority path):

```bash
sudo python3 -I -B scripts/nexolab-site-dr-preflight.py \
  --work-dir /var/backups/nexolab \
  --destination /mnt/OWNER_VERIFIED_SEPARATE_BACKUP_MEDIUM \
  --migration-authority runtime/object-storage-migration/authority.json
```

This script performs only Docker `ps -a --filter label=...`, targeted `inspect --format` on returned IDs, and targeted `volume inspect --format`. It does not use `docker exec`, Docker mutation, service restart, shell commands or environment-variable dumps. Only container ID *hashes*, immutable image digests, Compose service labels and named volume identities are retained in output. No host bind source paths, local-auth signing keys, sensor data, credentials, raw migration authority JSON, private customer data or volume contents are emitted.

- Exit 78 / `status=BLOCKED`: missing or changed service/volume/image/authority, wrong directory permissions, same-root destination, capacity shortage, ambiguous runtime mapping or missing verified cutover.
- Exit 0 / `source_inventory=observed_read_only`: only source identities and initial capacity preflight were observed. **This is not a release gate**.
- The JSON always states `backup_capture=not_performed`, `encrypted_off_device_copy=not_verified`, `isolated_restore=not_performed`, and `site_activation=not_authorized`.
- Local-auth **key-file existence, integrity, matching and secret custody remain unverified** by design. Central ingestion spool and edge MQTT durability remain `unclassified` until separately proven.
- Snapshot size caps are planning limits only. A maximum of 4 GiB staging is reserved on root on top of 20 GiB free. At least 16 GiB destination free space is required before planning; actual data sizes, full aggregate capacity and encryption must be proven separately before any transfer. No partial-copy or disk-pruning operations are allowed.

## Exact asset sources / protections

The inspected services and mounts must match the installed Compose declarations:

- PostgreSQL — `nexolab-central/postgres`, `nexolab-central-postgres-data`.
- Private S3 VersityGW — service key `nexolab-central/minio`, volume `nexolab-central-object-storage-versitygw-data`; requires matching verified `runtime/object-storage-migration/authority.json` cutover, target image digest and exact volume creation identity. Legacy MinIO storage cannot be silently substituted.
- Central MQTT Dynamic Security — `nexolab-central/mqtt`, `nexolab-central-mqtt-data`.
- Edge Device Agent SQLite/outbox — `nexolab-edge/device-agent`, `nexolab-edge_edge-data`.
- Local auth pair — `nexolab-central/telemetry-service`; private/public PEM presence and matches are **not** established.
- Central telemetry ingestion spool — `nexolab-central/telemetry-service`, `nexolab-central-telemetry-ingestion-data`.
- Edge MQTT persistence — `nexolab-edge/mqtt`, `nexolab-edge_mqtt-data`. The Compose service key `mqtt` is shared with the separate central project; both identities are required.

An unknown, missing or ambiguous identity blocks. A healthy Docker image and a structurally consistent preflight are not proof that live data are capturable or restorable.

## Operational follow-up and release boundary

1. Collect and independently review sanitized read-only evidence **on the actual site**, without writing to live volumes. If the destination does not exist or root-only custody is not confirmed, record the blocker and stop.
2. Separately implement protected service-specific capture procedures: bounded read-only logical `pg_dump`; VersityGW application-consistent objects/metadata; MQTT persistence and Dynamic Security with a vetted quiesce boundary; edge SQLite online backup with WAL and queue high-water integrity; RSA keypair through independent protected key custody. Do not implicitly stop devices or acquisition.
3. Obtain encrypted independent off-device copy and **verify restoration on a clean isolated host**, using the #1433 contract and checks from `docs/operations/site-dr-inventory-gate-1431.md`.
4. Only after full restore plus exact installed image/Compose/IPAM authority and rollback can #1399 seek separate Product Owner approval for protected Dashboard/API site recovery.

No Modbus/hardware write, service restart, DNS change or internet-dependent runtime is introduced. This package does not mean **🟢 Оновлюйся**.
