# NEXOLAB #1555 — verified cache-only cleanup of legacy fallback microSD

**Date:** 2026-11-10 (Europe/Warsaw, device EET)

**Host:** `nexolab-edge-01`
**Outcome:** Completed limited cache removal **on the separate, inactive microSD**, preserving the SSD production runtime and microSD emergency-boot image.

## Identity and safety gates

- Current running Linux root: `/dev/sda2`, PARTUUID `4299a96f-02`; `/boot/firmware` is `/dev/sda1` PARTUUID `4299a96f-01`.
- Physical legacy microSD: `/dev/mmcblk0` (62,226,694,144 bytes), `/dev/mmcblk0p1` (original FAT boot at `/media/nexolab/bootfs1`) and **unmounted** `/dev/mmcblk0p2` (ext4 PARTUUID `71ded8bc-02`, UUID `8abab6b9-ef90-4fee-ae3d-91079bfae7c1`).
- The old card's untouched `cmdline.txt` still references `root=PARTUUID=71ded8bc-02`. The live `/proc/cmdline` and `/etc/fstab` use the SSD only.
- Read-only inspection used `debugfs` and an isolated Docker mount with `ro,noload`; the previous root had ext4 clean state and a last mount date of 2026-09-08.
- Cleanup was performed with one isolated, no-network, read-only-container-root temporary mount namespace. **Only `/dev/mmcblk0p2` was passed as a writable block device**, with a temporary ext4 mount; no SSD block device or microSD FAT boot partition was writable from this container. Script guarded kernel root PARTUUID, SD major/minor (179,2), expected real directories and non-mount/non-symlink leaf paths.

## Exactly what was deleted

Only these regenerable cache trees **inside legacy `/dev/mmcblk0p2`**:

1. `/home/nexolab/.npm/_cacache` — npm download cache (read-only inventory: 395,508 KiB).
2. `/home/nexolab/.npm/_npx` — temporary npx packages (250,184 KiB).
3. `/home/nexolab/.cache/pip` — Python pip download cache (129,880 KiB).
4. Ten `*.deb` files immediately inside `/var/cache/apt/archives` (41,144 KiB for the archive directory prior to deletion); the directory, its `partial` directory and apt indexes were retained.

No shell wildcard was allowed to escape the exact apt archive directory. Other npm files (logs/config), Python environments, working `node_modules`, installed packages, service trees and the rest of the old operating system were not deleted.

## Actual space measurements

Measured **on the microSD ext4 filesystem** with `os.statvfs().f_bfree * f_frsize` before/after in the same mounted namespace:

| Metric                            |           Bytes |
| --------------------------------- | --------------: |
| microSD ext4 free blocks before   |   4,522,987,520 |
| microSD ext4 free blocks after    |   5,359,276,032 |
| **Actual additional free blocks** | **836,288,512** |

That delta is **797.55 MiB (~0.779 GiB)**. This is not space on the SSD. The source filesystem retains ext4 reserved blocks, so raw free-block counts are not equal to unprivileged `df Avail`.

## Verification actually executed

- Operation returned `OLD_OS_INTACT_CHECK_PASS`, `CLEAN_UNMOUNT_OK`, exit 0.
- Read-only post-run `debugfs` verified that the three cache directories no longer exist, the apt archive directory remains, and original `/etc`, `/home/nexolab/nexolab-platform`, and Docker volume directories remain accessible.
- Read-only `debugfs stats` after unmount: `Filesystem state: clean`, `Free blocks: 1308417`, `Free inodes: 2886790`.
- Live SSD `/dev/sda2` remains root: **81% used, ~43 GiB available** (post-run `df -B1` available 45,668,007,936 bytes). It did not gain the reclaimed microSD space.
- All 13 NEXOLAB containers still running; health-check-enabled units reported healthy. Two external frontend/nginx systemd units returned `active`. PostgreSQL telemetry `MAX(id)` at check: **13484021** (a successful new sample number, not a complete physical acceptance test).
- No production SQL deletion, Docker prune, production volume mutation, backup/rollback archive deletion, microSD partitioning/formatting, EEPROM/boot changes, service restart, Modbus write or industrial hardware write.

## Risks and next work

The old microSD is a **legacy boot/rollback source** established by #968 and remains the only identifiable removable rollback OS. It must not be erased while #1428 has not provided independently restored, complete eight-store backup evidence. If rebooted from microSD after an SSD failure, reusing development tools might require recreating download caches (but installed application files were preserved).

To gain **more SSD capacity**, cleanups must target verified unused SSD artifacts under separate protected recovery gates; deleting files on microSD will never increase SSD free space. #1428 controls protected backup/restore; #1551 controls evidence-safe ordinary telemetry retention. This work is not production deployment authorization.
