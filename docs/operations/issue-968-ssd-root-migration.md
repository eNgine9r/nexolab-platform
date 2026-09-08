# Issue #968 — migrate `nexolab-edge-01` root filesystem to the 256 GB SSD

## Purpose

Move the controlled NEXOLAB Raspberry Pi 5 from the nearly full microSD root filesystem to the approved Micron SSD without changing industrial polling semantics or deleting the microSD rollback source.

Approved target identity:

- stable path: `/dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5`;
- model: `Micron MTFDDAK256TBN`;
- serial: `17521B5686D5`;
- capacity: `256060514304` bytes / 238.5 GiB;
- transport observed on 2026-09-08: USB 3, UAS, 5 Gbit/s.

Source identity at preflight:

- root: `/dev/mmcblk0p2`;
- boot: `/dev/mmcblk0p1`;
- root usage: 97%, about 1.9 GB free;
- EEPROM boot order: `0xf461`, SD-first.

The migration helper refuses destructive operation unless the target model, serial, capacity class and current source-root identity match this boundary.

## Safety boundary

The Product Owner explicitly requested formatting the newly attached SSD and moving the NEXOLAB system to it. That approval applies only to the exact Micron SSD above.
Never:

- run the helper against `/dev/mmcblk0`;
- use `/dev/sdX` without the stable by-id path in the operator command;
- delete Docker named volumes;
- use `docker compose down -v`;
- perform Modbus/controller/hardware writes;
- erase or repartition the original microSD until SSD acceptance is complete.

The microSD remains the rollback medium.

## Phase 0 — recoverable working-tree snapshot

Before disk mutation, Issue #933 uncommitted work is captured outside the repository under:

`/home/nexolab/recovery/issue-968-pre-ssd-20260908T091750Z`

The directory contains a binary Git patch, untracked-file archive, disk inventory and SHA-256 manifest.

## Phase 1 — read-only preflight

Run without `sudo`:

```bash
cd /home/nexolab/nexolab-968
./scripts/migrate-raspberry-pi-root-to-ssd.sh preflight \
  --target-disk /dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5 \
  --expected-model 'Micron MTFDDAK256TBN' \
  --expected-serial '17521B5686D5'
```

Required result: `PRECHECK PASSED`. The report must still show active root `/dev/mmcblk0p2` and the approved SSD identity.

## Phase 2 — prepare the SSD

This phase is destructive only to the approved SSD. It:

1. unmounts existing SSD partitions;
2. removes the legacy Windows partition table/filesystem signatures;
3. creates a 512 MiB FAT32 boot partition and an ext4 root partition using the remaining capacity;
4. creates a compressed PostgreSQL logical backup and a SQLite backup-API snapshot on the SSD with SHA-256 evidence;
5. copies the complete current system, including `/home/nexolab` and `/var/lib/docker`, preserving owners, ACLs, xattrs, hardlinks and sparse files;
6. rewrites only the target copy of `fstab` and `cmdline.txt` to the new SSD PARTUUIDs;
7. leaves the current microSD runtime running and does not change EEPROM boot order.

Operator command:

```bash
cd /home/nexolab/nexolab-968
sudo ./scripts/migrate-raspberry-pi-root-to-ssd.sh prepare \
  --target-disk /dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5 \
  --expected-model 'Micron MTFDDAK256TBN' \
  --expected-serial '17521B5686D5'
```

Do not continue to cutover until the prepared filesystems, backup hashes, target `fstab` and target kernel `root=PARTUUID=` have been inspected.

### Prepared evidence — 2026-09-08

The Product Owner ran `prepare` against the exact approved Micron serial. Result: `PREPARE PASSED`. The prepared SSD has boot `PARTUUID=4299a96f-01`, root `PARTUUID=4299a96f-02`, and ext4 UUID `e704b091-7ce2-4d47-a049-64b19c0e709e`. Backup set `20260908T094149Z` contains a 473.2 MiB PostgreSQL custom archive plus a 256 KiB edge SQLite snapshot; all six recorded SHA-256 values revalidated independent of mount path, `pg_restore -l` exposed 494 archive entries, and SQLite `PRAGMA quick_check` returned `ok`. The target `fstab` and kernel cmdline contain no source microSD PARTUUID.

The seed copy covered 858,485 files / 55,174,431,322 bytes. During this high-I/O window the pre-existing Issue #933 SQLite lock-contention defect reproduced and Device Agent restarted to count 5 before recovering healthy. This observation does not invalidate the SSD filesystem preparation, but runtime health must be stable before the separate cutover.

## Phase 3 — controlled cutover

The cutover phase is intentionally separate. It revalidates the exact SSD identity and prepared backups, requires the critical PostgreSQL/Telemetry/MinIO/MQTT/Device Agent containers healthy, proves the Device Agent restart count remains unchanged across a bounded stability window, and requires Docker live-restore to be disabled. It then records every running container and its PID/restart policy, rejects any running container without `always` or `unless-stopped`, and quiesces the stack by stopping the Docker socket/daemon and containerd **without** issuing `docker stop`. This preserves restart eligibility for `restart: unless-stopped` containers while still proving every recorded container PID exited before the final filesystem sync. Only then does it switch boot order to NVMe/USB ahead of SD fallback and reboot.
Operator command:

```bash
cd /home/nexolab/nexolab-968
sudo ./scripts/migrate-raspberry-pi-root-to-ssd.sh cutover \
  --target-disk /dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5 \
  --expected-model 'Micron MTFDDAK256TBN' \
  --expected-serial '17521B5686D5'
```

If the helper fails before the boot-order/reboot commit point, its trap restarts Docker/containerd and the previously running containers.

## Phase 4 — SSD boot acceptance

After the host returns:

```bash
cd /home/nexolab/nexolab-968
sudo ./scripts/migrate-raspberry-pi-root-to-ssd.sh verify \
  --target-disk /dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5 \
  --expected-model 'Micron MTFDDAK256TBN' \
  --expected-serial '17521B5686D5'
```

Acceptance additionally verifies root/boot source, USB 3/UAS transport, larger root capacity, Docker volume identities, NEXOLAB service health, PostgreSQL/MinIO/MQTT/local auth, Device Agent queue and advancing read-only samples, and stable `/dev/serial/by-id/...` adapter identities.

A second controlled reboot is recommended before closing #968 so SSD boot persistence is proven independently of the first cutover boot.

## Rollback

If SSD boot or NEXOLAB readiness fails:

1. shut down the Raspberry Pi cleanly when possible;
2. disconnect the SSD or restore SD-first boot order;
3. boot from the untouched original microSD;
4. validate the original LOCAL_LAN runtime before further repair.

Do not modify the original microSD while SSD acceptance is unresolved.
