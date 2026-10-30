# NEXOLAB #1435 — read-only site DR preflight

**Source-only. No site activation or production data capture.**

This command observes source identities for the LOCAL_LAN multi-store recovery plan.
It does not capture data, move secrets, stop containers, restore services, or change Docker networking.
A passing observation is not an actual backup or disaster-recovery acceptance.

## Operator prerequisites

The operator must independently verify both paths and the installed source revision.

- Work directory: `/var/backups/nexolab`, owned by root, permissions `0700`.
- Destination: separately mounted filesystem, independently inspected, owned by root, permissions `0700`.
- Root headroom: at least 20 GiB free plus at most 4 GiB of proposed staging.
- Destination free space: at least 16 GiB.
- Verified VersityGW cutover authority at the installed repository location.

The old microSD partition is **not** an approved backup destination.
A separate filesystem does not prove physical disk independence or key custody.

## Example syntax

Use only an approved, already mounted independent destination:

```bash
sudo python3 -I -B scripts/nexolab-site-dr-preflight.py \
  --work-dir /var/backups/nexolab \
  --destination /mnt/OWNER_VERIFIED_BACKUP_MEDIUM \
  --migration-authority runtime/object-storage-migration/authority.json
```

The tool uses only scoped Docker `ps`, `inspect`, and `volume inspect` commands.
It does not print environment variables, host bind paths, key material, or volume contents.
The JSON report contains sanitized image/container identities and expected named volumes.

Exit 78 means `BLOCKED`. Exit 0 means only `observed_read_only`.
Neither result grants permission to perform backup capture or site recovery.
Every report retains these states:

- `backup_capture: not_performed`
- `encrypted_off_device_copy: not_verified`
- `isolated_restore: not_performed`
- `site_activation: not_authorized`

## Required source mapping

- PostgreSQL: `nexolab-central/postgres`; `nexolab-central-postgres-data`.
- VersityGW: `nexolab-central/minio`; `nexolab-central-object-storage-versitygw-data`.
- Central MQTT: `nexolab-central/mqtt`; `nexolab-central-mqtt-data`.
- Edge SQLite/outbox: `nexolab-edge/device-agent`; `nexolab-edge_edge-data`.
- Local auth: `nexolab-central/telemetry-service`; keypair presence remains unverified.
- Central ingestion spool: `nexolab-central/telemetry-service`; `nexolab-central-telemetry-ingestion-data`.
- Edge MQTT: `nexolab-edge/mqtt`; `nexolab-edge_mqtt-data`.

The `minio` service key is a compatibility name: the current backend is VersityGW.
The two `mqtt` services belong to different Compose projects.
Unknown, missing, duplicate, or changed protected sources block the inventory.

## Follow-up gates

1. Review actual source identities, offline destination, and key custody independently.
2. Implement consistent service-specific capture in a separate protected Work Package.
3. Verify encrypted off-device custody and full fresh-volume restore on an isolated host.
4. Obtain separate Product Owner approval for any #1399 Docker/IPAM recovery.

#1428 remains open until complete operational DR is proven.
#1433 defines the v2 receipt contract; #1431 documents the source inventory.
No Modbus or hardware write is allowed. **Do not signal an update to the Raspberry.**
