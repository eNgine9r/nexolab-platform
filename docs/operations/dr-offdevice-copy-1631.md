# #1631 DR-C — verified off-device copy and key custody

Parent: #1428. Order of the DR leaves: **A (#1630, scheduled encrypted backup) → C (#1631, this document) → B (#1632,
isolated restore)**.

> **Status: source and procedure only. NOTHING in this document has been executed on the Raspberry Pi, on a USB SSD,
> on a LAN workstation or on any other site hardware.** No real bundle was copied, no read-back was measured on real
> media, and no "internet disconnected" proof exists. The site evidence required by #1631 (real copy of a real leaf-A
> bundle, read-back SHA-256 equal to the source, custody receipt in DR evidence, offline proof) is **NOT produced by
> this work** and must be produced by the owner with the procedure below.

## What the tool does

`scripts/nexolab-dr-offdevice-copy.py` copies one verified leaf-A bundle (`nexolab-dr-*.nxs`, format
`nexolab-dr-stream-v1`) to a destination directory on independent media. It works without internet: it uses only the
local file system, `/proc`, `/sys` and `/dev/disk/by-uuid` (read-only). It never contacts Docker, the network or a
cloud API.

| Step                       | Rule (fail closed)                                                                                                                                                                                                                                                                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1. Key                     | The mounted key file must be a regular, non-symlink, `0600`, exactly 32-byte file (`nexolab-dr-stream.py` contract). It is read only to authenticate the bundle. It is **never** copied, printed or written. The receipt records only `sha256(key file bytes)`.                                                                                  |
| 2. Authenticate the bundle | The whole bundle is authenticated with the existing `nexolab-dr-stream.py` reader (AES-256-GCM STREAM, manifest and per-entry hashes). A wrong key, tampering or truncation refuses the copy **before** anything is written to the destination.                                                                                                  |
| 3. Destination identity    | The destination must be enrolled (`NEXOLAB-DR-DESTINATION.json`, see below), and the marker must belong to the volume it is found on: a moved or cloned marker is refused.                                                                                                                                                                       |
| 4. Independence            | Refused if the destination shares a **file system** (`st_dev`) or a **physical disk** with the source tree, the root file system or the key file, or if it lies inside (or contains) the source tree. Partitions resolve to their whole disk; loop and device-mapper devices resolve to their backing disks. Unidentifiable devices are refused. |
| 5. Copy                    | Encrypted bytes only are streamed to `.<name>.partial` (`0600`, `fsync`).                                                                                                                                                                                                                                                                        |
| 6. Read-back               | The **destination** file is re-read (page cache dropped where possible), and its size and SHA-256 are compared with the authenticated source **before** the atomic rename. A mismatch, short write, I/O error or interruption (including `SIGTERM`/`SIGINT`) removes the partial: an unverified file never gets the final name.                  |
| 7. Custody receipt         | A canonical `nexolab-dr-custody-receipt-v1` (`0600`) is written next to the bundle on the destination **and** into a local receipts directory, which must not be on the destination.                                                                                                                                                             |

Exit codes: `0` success, `1` verification/copy failure (nothing accepted), `78` blocked (key, enrolment, independence,
capacity or a stale partial from an earlier interrupted run).

A re-run is idempotent: an existing final file is accepted only after a fresh read-back matches; a different file under
the final name is never overwritten. A stale `.<name>.partial` left by a power loss is **not** deleted automatically;
inspect it and remove it by hand.

### Custody receipt `nexolab-dr-custody-receipt-v1`

Canonical JSON (sorted keys, no whitespace), exactly these fields. The isolated restore (#1632) consumes this contract;
do not rename fields.

| Field                         | Meaning                                                                                                                                                           |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`              | `1`                                                                                                                                                               |
| `kind`                        | `"nexolab-dr-custody-receipt"`                                                                                                                                    |
| `bundle_name`                 | leaf-A file name, `nexolab-dr-<UTC stamp>-<6 hex>.nxs`                                                                                                            |
| `bundle_sha256`               | SHA-256 of the exact source bytes that were cryptographically authenticated                                                                                       |
| `bundle_bytes`                | size of those bytes                                                                                                                                               |
| `source_manifest_sha256`      | SHA-256 of the canonical JSON of the decrypted in-stream manifest; recomputable after `nexolab-dr-stream.py verify`                                               |
| `destination_kind`            | `"dedicated_media"` (USB SSD) or `"independent_host"` (LAN share)                                                                                                 |
| `destination_identity_sha256` | SHA-256 of the canonical `{destination_id, destination_kind, label, volume_uuid}`: random enrolment id + label + file-system UUID (or share source), never a path |
| `source_disk_independent`     | `true` — written only after the independence check passed                                                                                                         |
| `readback_sha256`             | SHA-256 re-read from the destination file; must equal `bundle_sha256`                                                                                             |
| `readback_bytes`              | size re-read from the destination; must equal `bundle_bytes`                                                                                                      |
| `key_fingerprint_sha256`      | `sha256(key file bytes)` — never the key. (Not the same value as the 32-hex, domain-separated `key_fingerprint` in the stream header and the leaf-A receipt.)     |
| `copied_at`                   | UTC, seconds, `Z`                                                                                                                                                 |
| `copier`                      | `nexolab-dr-offdevice-copy.py/<version>`                                                                                                                          |
| `free_after_bytes`            | free bytes on the destination after the copy                                                                                                                      |

Mapping to `validate-site-dr-inventory-v2.py` `storage`: `off_device_copy_verified`, `source_disk_independent`,
`destination_kind`, `destination_identity_sha256` and `free_after_bytes` come from a re-verified custody receipt.
Note that the v2 contract also requires `free_after_bytes >= 20 GiB`, so the medium must be large enough (a 128 GB or
larger SSD). `independent_key_custody_verified` is **not** set by this tool: only the owner can attest it after the key
custody procedure below.

### Retention on the destination

`retention` is **report-only by default**. With `--apply` it deletes only verified bundles (receipt valid, bundle
re-hashes to it, same destination identity) beyond the newest `--keep` (minimum and default `2`), together with their
destination receipts. It never deletes the newest verified bundle, never touches unverified or unknown files, never
touches the local receipts directory, and refuses to run on a destination that is not independent of the root disk.
It never deletes anything on the Raspberry Pi: deletion of on-Pi backups is out of scope until #1632 has passed.

### Read-only health integration

`nexolab-dr-readonly-health.py --offdevice-destination <dir>` re-reads the newest bundle on the mounted destination
and compares it with its custody receipt (no key needed). Only a successful re-read sets `encrypted_off_device_copy`
to `REPORTED_OK`; a failed or unreadable destination sets it to `BLOCKED`; without the option it stays `UNVERIFIED`.
A receipt alone never changes the gate. The probe's overall status stays `BLOCKED` and `site_activation` stays
`NOT_AUTHORIZED`: re-reading a copy does not prove key custody, offline operation or a restore.

## Owner decisions still required

1. **Destination** (#1631 "Owner decision required before Ready"):
   - **Recommended:** a dedicated USB SSD (128 GB or larger, used for nothing else), attached on demand or rotated, and
     stored physically apart from the Pi. `destination_kind = dedicated_media`.
   - Alternative: an authorised LAN workstation exporting an offline-reachable share (SMB/NFS), mounted on the Pi.
     `destination_kind = independent_host`. The workstation must be online on the LAN when copying (see the
     2026-11-19 comment on #1428: it was offline).
   - Google Drive (#1619) may only ever be an **additional** copy, never the only one.
   - The old microSD (`mmcblk0`) is **not** an approved destination.
2. **Key custodians:** who holds the primary key and who holds the second custodian copy, and where (two different
   physical locations, neither of them the backup SSD).
3. **Copy cadence and media rotation** (for example weekly, two SSDs alternating).

## Key custody procedure

Rules:

- The key is stored **separately from every bundle copy**. The key never goes on the backup SSD or the LAN share; the
  tool refuses a key file on the destination disk.
- The key never goes into Git, GitHub, chat, tickets, logs or screenshots. Only fingerprints are recorded.
- **If every copy of the key is lost, every backup encrypted with it is permanently worthless.** There is no recovery,
  no back door and no way to decrypt the bundles. Losing the key is the same as having no backup at all.

Locations:

| Copy                      | Where                                                                                                                                                                                                                                     |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Primary (operational)     | `/etc/nexolab/dr-backup.key` on the Pi, `root:root 0600` (created in #1630 step 2). Needed by the scheduled backup and by this copy step.                                                                                                 |
| Second custodian (escrow) | **Owner decision.** Either a small separate USB stick used only for the key (not the backup SSD), or a paper copy of `base64` of the key in a sealed envelope. Kept at a different physical location from the Pi and from the backup SSD. |
| Custody register (no key) | A document that lists only: key fingerprints, creation date, custodians, locations, rotation dates. No key material.                                                                                                                      |

Owner steps (NOT executed):

```sh
# 1. Fingerprint the operational key (safe to record; reveals nothing about the key).
sudo sha256sum /etc/nexolab/dr-backup.key            # = key_fingerprint_sha256 in custody receipts

# 2a. Second custodian on a separate key-only USB stick (mounted at /mnt/key-escrow).
sudo install -m 0600 -o root -g root /etc/nexolab/dr-backup.key /mnt/key-escrow/nexolab-dr-backup.key
sudo sha256sum /mnt/key-escrow/nexolab-dr-backup.key # must equal step 1
sudo umount /mnt/key-escrow                          # then store the stick at the second location

# 2b. OR paper escrow: print once on an offline printer, never save the output to a file.
sudo base64 /etc/nexolab/dr-backup.key
```

Quarterly custody check (owner): confirm the escrow copy still exists and its `sha256sum` matches the register,
without bringing it next to the backup SSD.

### Key rotation path

The stream header binds every bundle to the key fingerprint, so old bundles always need their old key.

1. Generate a new key **only in an approved window**:
   `sudo sh -c 'umask 077; head -c 32 /dev/urandom > /etc/nexolab/dr-backup.key.new'`.
2. Put the new key into both custody locations (steps 2a/2b above) and add its fingerprint to the register.
3. Move the old key to `/etc/nexolab/dr-backup.key.<old fingerprint prefix>` and the new key to
   `/etc/nexolab/dr-backup.key` (both `0600`).
4. Take a new leaf-A backup, copy it with this tool, and pass an isolated restore (#1632) with the new key.
5. Keep the **old key in custody until every bundle encrypted with it has been retired** from every medium. Only then
   destroy the old key (and its escrow copies) and record that in the register.

If the key is suspected compromised: rotate immediately (steps 1–4). Bundles encrypted with the old key remain readable
by whoever holds it; retire them from all media once new-key bundles are verified.

### If the key is lost

1. Treat the site as having **no usable backup**: every bundle encrypted with the lost key is unrecoverable.
2. If any custodian copy still exists, restore the operational key from it and verify the fingerprint.
3. Otherwise generate a new key (rotation step 1), take a new leaf-A backup, copy it with this tool and pass an
   isolated restore (#1632) as soon as possible. Record the incident in #1428.

## Offline-capable copy procedure (owner-run, NOT executed)

All commands run on the Pi as root from a clean checkout of a merged `main`. Replace `/dev/sdX` after confirming the
device with `lsblk`; formatting erases the medium.

```sh
# 0. Offline proof: disconnect the Pi's internet uplink (WAN cable / router uplink), then record:
date -u +%Y-%m-%dT%H:%M:%SZ
ip route show default                       # expected: empty, or only the LAN gateway with no upstream
ping -c 1 -W 2 1.1.1.1; echo "exit=$?"      # expected: exit != 0

# 1. One-time preparation of a NEW, dedicated USB SSD (destructive for that SSD only).
lsblk -o NAME,SIZE,MODEL,SERIAL,MOUNTPOINT  # identify the SSD; it must NOT be sda (the Pi root SSD)
mkfs.ext4 -L nexolab-dr-a /dev/sdX1
mkdir -p /mnt/nexolab-dr
mount -o nodev,nosuid,noexec /dev/disk/by-label/nexolab-dr-a /mnt/nexolab-dr
install -d -m 0700 /mnt/nexolab-dr/nexolab
python3 -I -B scripts/nexolab-dr-offdevice-copy.py enroll \
  --destination /mnt/nexolab-dr/nexolab --kind dedicated_media --label nexolab-dr-a
# (LAN alternative: mount the authorised share, then --kind independent_host.)

# 2. Each copy: mount, copy the newest verified leaf-A bundle, re-verify, report retention, unmount.
mount -o nodev,nosuid,noexec /dev/disk/by-label/nexolab-dr-a /mnt/nexolab-dr
BUNDLE=$(ls -1 /var/backups/nexolab/dr/nexolab-dr-*.nxs | sort | tail -n 1)
python3 -I -B scripts/nexolab-dr-offdevice-copy.py copy \
  --bundle "$BUNDLE" \
  --source-receipt "${BUNDLE%.nxs}.receipt.json" \
  --key-file /etc/nexolab/dr-backup.key \
  --destination /mnt/nexolab-dr/nexolab \
  --receipts-dir /var/backups/nexolab/dr-custody
python3 -I -B scripts/nexolab-dr-offdevice-copy.py verify-destination --destination /mnt/nexolab-dr/nexolab
python3 -I -B scripts/nexolab-dr-offdevice-copy.py retention --destination /mnt/nexolab-dr/nexolab   # report only
python3 -I -B scripts/nexolab-dr-readonly-health.py --offdevice-destination /mnt/nexolab-dr/nexolab   # exit 78 by design
sync; umount /mnt/nexolab-dr                # then store the SSD apart from the Pi

# 3. Optional, separate decision: apply retention (keeps the newest 2 verified bundles).
python3 -I -B scripts/nexolab-dr-offdevice-copy.py retention --destination /mnt/nexolab-dr/nexolab --apply
```

Evidence to attach to #1631 (sanitized; no key material): the offline-proof output of step 0, the JSON printed by
`copy` and `verify-destination`, the custody receipt, the `sha256sum` of the source bundle next to the receipt's
`readback_sha256`, and the health probe output.

## Evidence status (this Work Package)

| Item                                                                                                          | Status                                    |
| ------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Tool, receipt contract, retention, health integration; synthetic tests (`tests/test_ci_dr_offdevice_copy.py`) | CI                                        |
| Owner decisions: destination, key custodians, cadence                                                         | **OPEN — owner decision required**        |
| Real copy of a real leaf-A bundle to the chosen media, read-back equal to the source                          | **NOT PERFORMED — site evidence missing** |
| Copy performed with the Pi's internet disconnected (offline proof)                                            | **NOT PERFORMED — site evidence missing** |
| Key custody established (second custodian location, register)                                                 | **NOT PERFORMED — owner action required** |
| `encrypted_off_device_copy` re-verified on site by the health probe                                           | **NOT PERFORMED**                         |
| Isolated restore from the off-device copy (#1632)                                                             | **UNVERIFIED**                            |
