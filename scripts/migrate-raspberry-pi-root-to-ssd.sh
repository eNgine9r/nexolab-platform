#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  migrate-raspberry-pi-root-to-ssd.sh MODE --target-disk PATH --expected-model MODEL --expected-serial SERIAL

Modes:
  preflight  Read-only identity/capacity/boot-order verification.
  prepare    DESTRUCTIVE: repartition/format target SSD, back up NEXOLAB, and seed-copy the current system.
  cutover    Final quiesced sync, configure SSD boot identity, set NVMe/USB-first boot order, and reboot.
  verify     Read-only post-boot verification.

Example for NEXOLAB Issue #968:
  sudo ./scripts/migrate-raspberry-pi-root-to-ssd.sh prepare \
    --target-disk /dev/disk/by-id/ata-Micron_MTFDDAK256TBN_17521B5686D5 \
    --expected-model 'Micron MTFDDAK256TBN' \
    --expected-serial '17521B5686D5'
EOF
}

MODE="${1:-}"
if [[ -z "$MODE" || "$MODE" == "-h" || "$MODE" == "--help" ]]; then
  usage
  exit 0
fi
shift

TARGET_DISK=""
EXPECTED_MODEL=""
EXPECTED_SERIAL=""
while (($#)); do
  case "$1" in
    --target-disk) TARGET_DISK="${2:-}"; shift 2 ;;
    --expected-model) EXPECTED_MODEL="${2:-}"; shift 2 ;;
    --expected-serial) EXPECTED_SERIAL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MODE" in
  preflight|prepare|cutover|verify) ;;
  *) echo "ERROR: MODE must be preflight, prepare, cutover, or verify" >&2; exit 2 ;;
esac

fail() { echo "ERROR: $*" >&2; exit 1; }
log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
need() { command -v "$1" >/dev/null 2>&1 || fail "required command missing: $1"; }
trim() { awk '{$1=$1};1'; }

for cmd in lsblk findmnt blkid readlink awk sed grep sha256sum; do need "$cmd"; done
[[ -n "$TARGET_DISK" ]] || fail "--target-disk is required"
[[ -n "$EXPECTED_MODEL" ]] || fail "--expected-model is required"
[[ -n "$EXPECTED_SERIAL" ]] || fail "--expected-serial is required"
[[ -e "$TARGET_DISK" ]] || fail "target disk path does not exist: $TARGET_DISK"
TARGET_DEVICE="$(readlink -f -- "$TARGET_DISK")"
[[ -b "$TARGET_DEVICE" ]] || fail "target does not resolve to a block device: $TARGET_DEVICE"
[[ "$(lsblk -dn -o TYPE "$TARGET_DEVICE" | trim)" == "disk" ]] || fail "target is not a whole disk"

ACTUAL_MODEL="$(lsblk -dn -o MODEL "$TARGET_DEVICE" | trim)"
ACTUAL_SERIAL="$(lsblk -dn -o SERIAL "$TARGET_DEVICE" | trim)"
ACTUAL_SIZE="$(lsblk -bdn -o SIZE "$TARGET_DEVICE" | trim)"
[[ "$ACTUAL_MODEL" == "$EXPECTED_MODEL" ]] || fail "model mismatch: expected '$EXPECTED_MODEL', got '$ACTUAL_MODEL'"
[[ "$ACTUAL_SERIAL" == "$EXPECTED_SERIAL" ]] || fail "serial mismatch: expected '$EXPECTED_SERIAL', got '$ACTUAL_SERIAL'"
[[ "$ACTUAL_SIZE" =~ ^[0-9]+$ ]] || fail "cannot determine target size"
(( ACTUAL_SIZE >= 200000000000 && ACTUAL_SIZE <= 300000000000 )) || fail "target size outside approved 256 GB class: $ACTUAL_SIZE bytes"

ROOT_SOURCE="$(findmnt -n -o SOURCE /)"
BOOT_SOURCE="$(findmnt -n -o SOURCE /boot/firmware 2>/dev/null || true)"
ROOT_REAL="$(readlink -f -- "$ROOT_SOURCE" 2>/dev/null || printf '%s' "$ROOT_SOURCE")"
ROOT_PARENT="/dev/$(lsblk -no PKNAME "$ROOT_REAL" 2>/dev/null | head -1)"
if [[ "$MODE" != "verify" ]]; then
  [[ "$ROOT_REAL" != "$TARGET_DEVICE" ]] || fail "target disk is the active root device"
  [[ "$ROOT_PARENT" != "$TARGET_DEVICE" ]] || fail "target disk contains the active root partition"
fi

partition_path() {
  local disk="$1" n="$2"
  if [[ "$disk" =~ [0-9]$ ]]; then printf '%sp%s' "$disk" "$n"; else printf '%s%s' "$disk" "$n"; fi
}
P1="$(partition_path "$TARGET_DEVICE" 1)"
P2="$(partition_path "$TARGET_DEVICE" 2)"
TARGET_ROOT=/mnt/nexolab-ssd-root

identity_report() {
  log "mode=$MODE"
  log "active_root=$ROOT_SOURCE"
  log "active_boot=${BOOT_SOURCE:-unknown}"
  log "target=$TARGET_DEVICE model=$ACTUAL_MODEL serial=$ACTUAL_SERIAL size_bytes=$ACTUAL_SIZE"
  lsblk -e7 -o NAME,PATH,MODEL,SERIAL,SIZE,TYPE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINTS,TRAN "$TARGET_DEVICE" "$ROOT_PARENT" 2>/dev/null || true
  if command -v lsusb >/dev/null 2>&1; then lsusb -t || true; fi
  if command -v rpi-eeprom-config >/dev/null 2>&1; then rpi-eeprom-config | grep -E '^BOOT_ORDER=' || true; fi
}

if [[ "$MODE" == "preflight" ]]; then
  identity_report
  [[ "$ROOT_REAL" == /dev/mmcblk0p2 ]] || fail "Issue #968 preflight expected active root /dev/mmcblk0p2; got $ROOT_REAL"
  log "PRECHECK PASSED: target identity is approved and distinct from active microSD"
  exit 0
fi

if [[ "$MODE" == "verify" ]]; then
  identity_report
  ROOT_PARENT_NOW="/dev/$(lsblk -no PKNAME "$ROOT_REAL" 2>/dev/null | head -1)"
  [[ "$ROOT_PARENT_NOW" == "$TARGET_DEVICE" ]] || fail "root is not running from approved SSD: root=$ROOT_REAL parent=$ROOT_PARENT_NOW"
  BOOT_REAL="$(readlink -f -- "$BOOT_SOURCE" 2>/dev/null || printf '%s' "$BOOT_SOURCE")"
  BOOT_PARENT_NOW="/dev/$(lsblk -no PKNAME "$BOOT_REAL" 2>/dev/null | head -1)"
  [[ "$BOOT_PARENT_NOW" == "$TARGET_DEVICE" ]] || fail "boot filesystem is not running from approved SSD"
  VERIFY_MARKER=/var/backups/nexolab/issue-968-prepared.marker
  [[ -f "$VERIFY_MARKER" ]] || fail "Issue #968 prepare marker is missing from active SSD root"
  grep -qx "target_serial=$ACTUAL_SERIAL" "$VERIFY_MARKER" || fail "active SSD prepare marker serial mismatch"
  df -hT /
  if command -v docker >/dev/null 2>&1; then docker ps --format 'table {{.Names}}\t{{.Status}}'; fi
  log "VERIFY PASSED: root and boot are SSD-backed"
  exit 0
fi

(( EUID == 0 )) || fail "$MODE requires root privileges"
for cmd in sfdisk wipefs mkfs.vfat mkfs.ext4 mount umount mountpoint rsync udevadm partprobe sync docker systemctl find sort tail wc python3; do need "$cmd"; done
[[ "$ROOT_REAL" == /dev/mmcblk0p2 ]] || fail "Issue #968 mutation expected active root /dev/mmcblk0p2; got $ROOT_REAL"

RUNTIME_STOPPED=0
CUTOVER_COMMITTED=0
RUNNING_FILE=""
cleanup() {
  local rc=$?
  set +e
  if mountpoint -q "$TARGET_ROOT/boot/firmware" 2>/dev/null; then umount "$TARGET_ROOT/boot/firmware"; fi
  if mountpoint -q "$TARGET_ROOT" 2>/dev/null; then umount "$TARGET_ROOT"; fi
  if (( RUNTIME_STOPPED == 1 && CUTOVER_COMMITTED == 0 )); then
    systemctl start containerd.service >/dev/null 2>&1 || true
    systemctl start docker.service >/dev/null 2>&1 || true
    if [[ -n "$RUNNING_FILE" && -s "$RUNNING_FILE" ]]; then
      while IFS= read -r c; do [[ -n "$c" ]] && docker start "$c" >/dev/null 2>&1 || true; done < "$RUNNING_FILE"
    fi
  fi
  exit "$rc"
}
trap cleanup EXIT

unmount_target_children() {
  while IFS= read -r part; do
    [[ -n "$part" ]] || continue
    while IFS= read -r mp; do
      [[ -n "$mp" ]] || continue
      log "Unmounting target child $part from $mp"
      umount "$mp"
    done < <(findmnt -rn -S "$part" -o TARGET 2>/dev/null || true)
  done < <(lsblk -ln -o PATH "$TARGET_DEVICE" | tail -n +2)
}

mount_target() {
  mkdir -p "$TARGET_ROOT"
  mount "$P2" "$TARGET_ROOT"
  mkdir -p "$TARGET_ROOT/boot/firmware"
  mount "$P1" "$TARGET_ROOT/boot/firmware"
}

root_rsync() {
  rsync -aHAXSx --numeric-ids --delete --info=stats2 \
    --exclude='/dev/***' \
    --exclude='/proc/***' \
    --exclude='/sys/***' \
    --exclude='/run/***' \
    --exclude='/tmp/***' \
    --exclude='/mnt/***' \
    --exclude='/media/***' \
    --exclude='/lost+found' \
    --exclude='/boot/firmware/***' \
    --exclude='/var/backups/nexolab/issue-968-ssd-migration/***' \
    --exclude='/var/backups/nexolab/issue-968-partuuid-map.txt' \
    --exclude='/var/backups/nexolab/issue-968-prepared.marker' \
    / "$TARGET_ROOT/"
  # The boot filesystem is FAT32; do not request Unix ACL/xattr/owner preservation there.
  rsync -rt --delete --modify-window=1 /boot/firmware/ "$TARGET_ROOT/boot/firmware/"
}

configure_target_boot() {
  local old_root_partuuid old_boot_partuuid new_root_partuuid new_boot_partuuid cmdline fstab
  old_root_partuuid="$(blkid -s PARTUUID -o value "$ROOT_REAL")"
  old_boot_partuuid="$(blkid -s PARTUUID -o value "$(readlink -f -- "$BOOT_SOURCE")")"
  new_root_partuuid="$(blkid -s PARTUUID -o value "$P2")"
  new_boot_partuuid="$(blkid -s PARTUUID -o value "$P1")"
  [[ -n "$old_root_partuuid" && -n "$old_boot_partuuid" && -n "$new_root_partuuid" && -n "$new_boot_partuuid" ]] || fail "missing PARTUUID while configuring target"
  [[ "$old_root_partuuid" != "$new_root_partuuid" ]] || fail "target root PARTUUID unexpectedly matches source"
  fstab="$TARGET_ROOT/etc/fstab"
  cmdline="$TARGET_ROOT/boot/firmware/cmdline.txt"
  [[ -f "$fstab" && -f "$cmdline" ]] || fail "target boot configuration files missing"
  grep -q "PARTUUID=$old_root_partuuid" "$fstab" || fail "source root PARTUUID not found in target fstab"
  grep -q "PARTUUID=$old_boot_partuuid" "$fstab" || fail "source boot PARTUUID not found in target fstab"
  grep -q "root=PARTUUID=$old_root_partuuid" "$cmdline" || fail "source root PARTUUID not found in target cmdline"
  sed -i "s/PARTUUID=$old_root_partuuid/PARTUUID=$new_root_partuuid/g; s/PARTUUID=$old_boot_partuuid/PARTUUID=$new_boot_partuuid/g" "$fstab"
  sed -i "s/root=PARTUUID=$old_root_partuuid/root=PARTUUID=$new_root_partuuid/g" "$cmdline"
  grep -q "PARTUUID=$new_root_partuuid" "$fstab" || fail "new root PARTUUID missing from target fstab"
  grep -q "PARTUUID=$new_boot_partuuid" "$fstab" || fail "new boot PARTUUID missing from target fstab"
  grep -q "root=PARTUUID=$new_root_partuuid" "$cmdline" || fail "new root PARTUUID missing from target cmdline"
  printf 'source_root_partuuid=%s\nsource_boot_partuuid=%s\ntarget_root_partuuid=%s\ntarget_boot_partuuid=%s\n' \
    "$old_root_partuuid" "$old_boot_partuuid" "$new_root_partuuid" "$new_boot_partuuid" \
    > "$TARGET_ROOT/var/backups/nexolab/issue-968-partuuid-map.txt"
}

write_prepare_marker() {
  local root_partuuid boot_partuuid marker
  root_partuuid="$(blkid -s PARTUUID -o value "$P2")"
  boot_partuuid="$(blkid -s PARTUUID -o value "$P1")"
  marker="$TARGET_ROOT/var/backups/nexolab/issue-968-prepared.marker"
  mkdir -p "$(dirname "$marker")"
  printf 'issue=968\ntarget_model=%s\ntarget_serial=%s\nroot_partuuid=%s\nboot_partuuid=%s\n' \
    "$ACTUAL_MODEL" "$ACTUAL_SERIAL" "$root_partuuid" "$boot_partuuid" > "$marker"
}

validate_prepare_marker() {
  local marker="$TARGET_ROOT/var/backups/nexolab/issue-968-prepared.marker"
  [[ -f "$marker" ]] || fail "Issue #968 prepare marker is missing"
  grep -qx 'issue=968' "$marker" || fail "prepare marker issue mismatch"
  grep -qx "target_model=$ACTUAL_MODEL" "$marker" || fail "prepare marker model mismatch"
  grep -qx "target_serial=$ACTUAL_SERIAL" "$marker" || fail "prepare marker serial mismatch"
  grep -qx "root_partuuid=$(blkid -s PARTUUID -o value "$P2")" "$marker" || fail "prepare marker root PARTUUID mismatch"
  grep -qx "boot_partuuid=$(blkid -s PARTUUID -o value "$P1")" "$marker" || fail "prepare marker boot PARTUUID mismatch"
}

quiesce_runtime() {
  RUNNING_FILE="$(mktemp)"
  docker ps --format '{{.Names}}' | sort > "$RUNNING_FILE"
  if [[ -s "$RUNNING_FILE" ]]; then
    mapfile -t running < "$RUNNING_FILE"
    log "Stopping ${#running[@]} running Docker containers for filesystem-consistent sync"
    docker stop --time 45 "${running[@]}" >/dev/null
  fi
  systemctl stop docker.service docker.socket >/dev/null 2>&1 || true
  systemctl stop containerd.service >/dev/null 2>&1 || true
  RUNTIME_STOPPED=1
}

restore_runtime() {
  systemctl start containerd.service >/dev/null 2>&1 || true
  systemctl start docker.service >/dev/null 2>&1 || true
  if [[ -n "$RUNNING_FILE" && -s "$RUNNING_FILE" ]]; then
    while IFS= read -r c; do [[ -n "$c" ]] && docker start "$c" >/dev/null 2>&1 || true; done < "$RUNNING_FILE"
  fi
  RUNTIME_STOPPED=0
}

create_live_backups() {
  local backup_dir="$1" pg_tmp edge_tmp
  mkdir -p "$backup_dir"
  git -C /home/nexolab/nexolab-platform status --porcelain=v1 > "$backup_dir/active-working-tree-status.txt" 2>/dev/null || true
  git -C /home/nexolab/nexolab-platform diff --binary > "$backup_dir/active-working-tree.patch" 2>/dev/null || true
  docker ps --format '{{.Names}} {{.Image}} {{.Status}}' > "$backup_dir/docker-containers.txt"
  docker volume ls --format '{{.Name}}' | sort > "$backup_dir/docker-volumes.txt"

  if docker inspect nexolab-central-postgres-1 >/dev/null 2>&1 && [[ "$(docker inspect -f '{{.State.Running}}' nexolab-central-postgres-1)" == true ]]; then
    pg_tmp="$backup_dir/postgresql.dump.partial"
    docker exec nexolab-central-postgres-1 sh -ceu 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$pg_tmp"
    [[ -s "$pg_tmp" ]] || fail "PostgreSQL backup is empty"
    mv "$pg_tmp" "$backup_dir/postgresql.dump"
    docker exec -i nexolab-central-postgres-1 pg_restore -l < "$backup_dir/postgresql.dump" >/dev/null
  else
    fail "running NEXOLAB PostgreSQL container not found"
  fi

  if docker inspect nexolab-edge-device-agent-1 >/dev/null 2>&1 && [[ "$(docker inspect -f '{{.State.Running}}' nexolab-edge-device-agent-1)" == true ]]; then
    edge_tmp="/tmp/issue-968-edge-pre-ssd.db"
    docker exec nexolab-edge-device-agent-1 python3 -c 'import sqlite3; src=sqlite3.connect("file:/var/lib/nexolab/edge.db?mode=ro", uri=True); dst=sqlite3.connect("/tmp/issue-968-edge-pre-ssd.db"); src.backup(dst); print(dst.execute("PRAGMA quick_check").fetchone()[0]); dst.close(); src.close()' | grep -qx ok
    docker cp "nexolab-edge-device-agent-1:$edge_tmp" "$backup_dir/edge.db" >/dev/null
    docker exec nexolab-edge-device-agent-1 python3 -c 'import os; os.remove("/tmp/issue-968-edge-pre-ssd.db")'
    [[ -s "$backup_dir/edge.db" ]] || fail "edge SQLite backup is empty"
  else
    fail "running NEXOLAB Device Agent container not found"
  fi
  (
    cd "$backup_dir"
    sha256sum active-working-tree.patch active-working-tree-status.txt docker-containers.txt docker-volumes.txt edge.db postgresql.dump > SHA256SUMS
  )
}

validate_prepared_backups() {
  local backup_root latest manifest file expected actual matches
  backup_root="$TARGET_ROOT/var/backups/nexolab/issue-968-ssd-migration"
  [[ -d "$backup_root" ]] || fail "Issue #968 backup root is missing"
  latest="$(find "$backup_root" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
  [[ -n "$latest" && -f "$latest/SHA256SUMS" ]] || fail "Issue #968 checksum manifest is missing"
  manifest="$latest/SHA256SUMS"
  for file in active-working-tree.patch active-working-tree-status.txt docker-containers.txt docker-volumes.txt edge.db postgresql.dump; do
    [[ -f "$latest/$file" ]] || fail "prepared backup file is missing: $file"
    matches="$(awk -v name="$file" '{p=$2; sub(/^.*\//, "", p); if (p == name) print $1}' "$manifest")"
    [[ "$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l)" -eq 1 ]] || fail "checksum manifest does not contain exactly one entry for $file"
    expected="$matches"
    actual="$(sha256sum "$latest/$file" | awk '{print $1}')"
    [[ "$actual" == "$expected" ]] || fail "checksum mismatch for prepared backup: $file"
  done
  docker exec -i nexolab-central-postgres-1 pg_restore -l < "$latest/postgresql.dump" >/dev/null || fail "prepared PostgreSQL dump is not a readable custom archive"
  python3 - "$latest/edge.db" <<'PY_SQLITE'
import sqlite3
import sys
path = sys.argv[1]
connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
try:
    result = connection.execute("PRAGMA quick_check").fetchone()[0]
finally:
    connection.close()
if result != "ok":
    raise SystemExit(f"edge SQLite quick_check failed: {result}")
PY_SQLITE
  log "Prepared backup validation passed: checksums, PostgreSQL archive, edge SQLite quick_check"
}

if [[ "$MODE" == "prepare" ]]; then
  identity_report
  log "DESTRUCTIVE SCOPE CONFIRMED: only $TARGET_DEVICE serial=$ACTUAL_SERIAL will be repartitioned"
  unmount_target_children
  wipefs --all --force "$TARGET_DEVICE"
  printf 'label: dos\nunit: sectors\n\nstart=8192,size=1048576,type=c,bootable\nstart=1056768,type=83\n' | sfdisk --wipe always --wipe-partitions always "$TARGET_DEVICE"
  partprobe "$TARGET_DEVICE" || true
  udevadm settle
  [[ -b "$P1" && -b "$P2" ]] || fail "target partitions did not appear"
  mkfs.vfat -F 32 -n bootfs "$P1"
  mkfs.ext4 -F -L rootfs "$P2"
  udevadm settle
  unmount_target_children
  mount_target
  STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
  BACKUP_DIR="$TARGET_ROOT/var/backups/nexolab/issue-968-ssd-migration/$STAMP"
  create_live_backups "$BACKUP_DIR"
  log "Starting seed system copy"
  root_rsync
  configure_target_boot
  write_prepare_marker
  validate_prepare_marker
  sync
  log "PREPARE PASSED: SSD is formatted, backed up, and seed-copied. Production containers remained running; no boot-order change or reboot performed."
  exit 0
fi

if [[ "$MODE" == "cutover" ]]; then
  identity_report
  [[ -b "$P1" && -b "$P2" ]] || fail "prepared SSD partitions are missing"
  [[ "$(blkid -s TYPE -o value "$P1")" == "vfat" ]] || fail "target boot partition is not vfat"
  [[ "$(blkid -s TYPE -o value "$P2")" == "ext4" ]] || fail "target root partition is not ext4"
  mount_target
  validate_prepare_marker
  validate_prepared_backups
  log "Quiescing Docker for final cutover sync"
  quiesce_runtime
  root_rsync
  configure_target_boot
  write_prepare_marker
  validate_prepare_marker
  sync
  umount "$TARGET_ROOT/boot/firmware"
  umount "$TARGET_ROOT"
  need raspi-config
  log "Setting Raspberry Pi boot order to NVMe/USB before SD fallback (B2)"
  raspi-config nonint do_boot_order B2
  log "CUTOVER READY: rebooting now. Original microSD remains untouched as rollback media."
  if systemctl reboot; then
    CUTOVER_COMMITTED=1
  else
    fail "reboot request failed after boot-order update; runtime recovery will be attempted"
  fi
  exit 0
fi
