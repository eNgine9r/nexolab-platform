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
  (( EUID == 0 )) || fail "verify requires root privileges"
  for cmd in docker timeout python3 udevadm find sort comm curl lsusb df awk tail wc; do need "$cmd"; done
  identity_report
  ROOT_PARENT_NOW="/dev/$(lsblk -no PKNAME "$ROOT_REAL" 2>/dev/null | head -1)"
  [[ "$ROOT_PARENT_NOW" == "$TARGET_DEVICE" ]] || fail "root is not running from approved SSD: root=$ROOT_REAL parent=$ROOT_PARENT_NOW"
  BOOT_REAL="$(readlink -f -- "$BOOT_SOURCE" 2>/dev/null || printf '%s' "$BOOT_SOURCE")"
  BOOT_PARENT_NOW="/dev/$(lsblk -no PKNAME "$BOOT_REAL" 2>/dev/null | head -1)"
  [[ "$BOOT_PARENT_NOW" == "$TARGET_DEVICE" ]] || fail "boot filesystem is not running from approved SSD"
  VERIFY_MARKER=/var/backups/nexolab/issue-968-prepared.marker
  [[ -f "$VERIFY_MARKER" ]] || fail "Issue #968 prepare marker is missing from active SSD root"
  grep -qx "target_serial=$ACTUAL_SERIAL" "$VERIFY_MARKER" || fail "active SSD prepare marker serial mismatch"
  grep -qx "root_partuuid=$(blkid -s PARTUUID -o value "$ROOT_REAL")" "$VERIFY_MARKER" || fail "active SSD root PARTUUID does not match prepare marker"
  grep -qx "boot_partuuid=$(blkid -s PARTUUID -o value "$BOOT_REAL")" "$VERIFY_MARKER" || fail "active SSD boot PARTUUID does not match prepare marker"

  ROOT_BYTES="$(df -B1 --output=size / | tail -1 | trim)"
  [[ "$ROOT_BYTES" =~ ^[0-9]+$ ]] || fail "cannot determine active root filesystem capacity"
  (( ROOT_BYTES >= 200000000000 )) || fail "active root filesystem is smaller than expected SSD capacity: $ROOT_BYTES bytes"
  UDEV_PROPERTIES="$(udevadm info -q property -n "$TARGET_DEVICE")" || fail "cannot read SSD udev properties"
  grep -qx 'ID_USB_DRIVER=uas' <<< "$UDEV_PROPERTIES" || fail "approved SSD is not using UAS"
  lsusb -t | grep -Eq 'Mass Storage, Driver=uas, 5000M' || fail "USB 3 / UAS 5 Gbit/s transport not observed"

  for adapter in \
    /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0 \
    /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F246-if00-port0; do
    [[ -L "$adapter" ]] || fail "stable RS-485 adapter identity missing: $adapter"
    [[ -c "$(readlink -f -- "$adapter")" ]] || fail "stable RS-485 adapter does not resolve to a character device: $adapter"
  done

  BACKUP_ROOT=/var/backups/nexolab/issue-968-ssd-migration
  LATEST_BACKUP="$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
  [[ -n "$LATEST_BACKUP" && -f "$LATEST_BACKUP/docker-volumes.txt" && -f "$LATEST_BACKUP/docker-containers.txt" ]] || fail "prepared runtime inventory is missing from SSD"
  CURRENT_VOLUMES="$(mktemp)"
  docker volume ls --format '{{.Name}}' | sort > "$CURRENT_VOLUMES"
  MISSING_VOLUMES="$(comm -23 "$LATEST_BACKUP/docker-volumes.txt" "$CURRENT_VOLUMES")"
  rm -f "$CURRENT_VOLUMES"
  [[ -z "$MISSING_VOLUMES" ]] || fail "Docker volumes missing after SSD boot: $MISSING_VOLUMES"

  while read -r name _; do
    [[ -n "$name" ]] || continue
    state="$(timeout 15s docker inspect -f '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name")" || fail "prepared container missing after SSD boot: $name"
    [[ "$state" == 'true|healthy' || "$state" == 'true|none' ]] || fail "prepared container is not running/healthy after SSD boot: $name ($state)"
  done < "$LATEST_BACKUP/docker-containers.txt"

  timeout 15s docker exec nexolab-central-postgres-1 sh -ceu 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null || fail "PostgreSQL readiness failed after SSD boot"
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3000/)" == 200 ]] || fail "Dashboard root is not HTTP 200 after SSD boot"
  [[ "$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3000/login)" == 200 ]] || fail "Local login surface is not HTTP 200 after SSD boot"
  AUTH_SESSION_CODE="$(timeout 15s docker exec nexolab-central-telemetry-service-1 python3 -c 'import urllib.request,urllib.error; req=urllib.request.Request("http://127.0.0.1:8082/api/v1/auth/session");
try:
 urllib.request.urlopen(req,timeout=5); print(200)
except urllib.error.HTTPError as e:
 print(e.code)')" || fail "local auth session route probe failed"
  [[ "$AUTH_SESSION_CODE" == 401 ]] || fail "local auth session route did not fail closed with HTTP 401: $AUTH_SESSION_CODE"

  agent_snapshot() {
    timeout 15s docker exec nexolab-edge-device-agent-1 python3 -c 'import json,urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8081/health",timeout=5)); s=d.get("acquisition",{}).get("scheduler",{}); print("|".join(map(str,[d.get("samples_total",-1),d.get("last_sample_at") or "",str(bool(d.get("mqtt_connected"))).lower(),d.get("queue_size",d.get("queue_depth",-1)),s.get("expected_bus_workers",-1),s.get("active_bus_workers",-1),str(bool(s.get("workers_healthy"))).lower()])))'
  }
  IFS='|' read -r samples_before sample_at_before mqtt_before queue_before expected_before active_before workers_before <<< "$(agent_snapshot)"
  restart_before="$(timeout 15s docker inspect -f '{{.RestartCount}}' nexolab-edge-device-agent-1)" || fail "cannot read Device Agent restart count during SSD verification"
  sleep 40
  IFS='|' read -r samples_after sample_at_after mqtt_after queue_after expected_after active_after workers_after <<< "$(agent_snapshot)"
  restart_after="$(timeout 15s docker inspect -f '{{.RestartCount}}' nexolab-edge-device-agent-1)" || fail "cannot re-read Device Agent restart count during SSD verification"
  [[ "$samples_before" =~ ^[0-9]+$ && "$samples_after" =~ ^[0-9]+$ && "$samples_after" -gt "$samples_before" ]] || fail "Device Agent samples did not advance after SSD boot: $samples_before -> $samples_after"
  [[ -n "$sample_at_before" && -n "$sample_at_after" && "$sample_at_after" != "$sample_at_before" ]] || fail "Device Agent last_sample_at did not advance after SSD boot"
  [[ "$mqtt_before" == true && "$mqtt_after" == true ]] || fail "Device Agent MQTT is not continuously connected after SSD boot"
  [[ "$queue_before" =~ ^[0-9]+$ && "$queue_after" =~ ^[0-9]+$ && "$queue_before" -le 10 && "$queue_after" -le 10 ]] || fail "Device Agent queue is not bounded after SSD boot: $queue_before -> $queue_after"
  [[ "$expected_before" =~ ^[1-9][0-9]*$ && "$expected_before" == "$active_before" && "$expected_after" == "$active_after" && "$expected_before" == "$expected_after" ]] || fail "Device Agent bus workers are incomplete after SSD boot"
  [[ "$workers_before" == true && "$workers_after" == true ]] || fail "Device Agent bus workers are not healthy after SSD boot"
  [[ "$restart_before" == "$restart_after" ]] || fail "Device Agent restarted during SSD verification: $restart_before -> $restart_after"

  df -hT /
  docker ps --format 'table {{.Names}}\t{{.Status}}'
  log "VERIFY PASSED: SSD root/boot, UAS transport, volumes, services, local auth surface, RS-485 identities, and advancing acquisition are healthy"
  exit 0
fi

(( EUID == 0 )) || fail "$MODE requires root privileges"
for cmd in sfdisk wipefs mkfs.vfat mkfs.ext4 mount umount mountpoint rsync udevadm partprobe sync docker systemctl find sort tail wc python3 timeout sleep; do need "$cmd"; done
[[ "$ROOT_REAL" == /dev/mmcblk0p2 ]] || fail "Issue #968 mutation expected active root /dev/mmcblk0p2; got $ROOT_REAL"

RUNTIME_STOPPED=0
CUTOVER_COMMITTED=0
RUNNING_FILE=""
RUNNING_PID_FILE=""
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

require_healthy_container() {
  local name="$1" state
  state="$(timeout 15s docker inspect -f '{{.State.Running}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name")" || fail "cannot inspect required container: $name"
  [[ "$state" == 'true|healthy' ]] || fail "required container is not running/healthy: $name ($state)"
}

validate_pre_cutover_runtime() {
  local restart_before restart_after live_restore
  for name in nexolab-central-postgres-1 nexolab-central-telemetry-service-1 nexolab-central-minio-1 nexolab-central-mqtt-1 nexolab-edge-mqtt-1 nexolab-edge-device-agent-1; do
    require_healthy_container "$name"
  done
  live_restore="$(timeout 15s docker info --format '{{.LiveRestoreEnabled}}')" || fail "cannot read Docker live-restore state"
  [[ "$live_restore" == false ]] || fail "Docker live-restore must be disabled for daemon-level filesystem quiesce"
  restart_before="$(timeout 15s docker inspect -f '{{.RestartCount}}' nexolab-edge-device-agent-1)" || fail "cannot read Device Agent restart count"
  sleep 10
  require_healthy_container nexolab-edge-device-agent-1
  restart_after="$(timeout 15s docker inspect -f '{{.RestartCount}}' nexolab-edge-device-agent-1)" || fail "cannot re-read Device Agent restart count"
  [[ "$restart_after" == "$restart_before" ]] || fail "Device Agent restarted during pre-cutover stability window: $restart_before -> $restart_after"
  log "Pre-cutover runtime validation passed: required services healthy, live-restore disabled, Device Agent restart count stable at $restart_after"
}

quiesce_runtime() {
  local name policy pid
  RUNNING_FILE="$(mktemp)"
  RUNNING_PID_FILE="$(mktemp)"
  timeout 20s docker ps --format '{{.Names}}' | sort > "$RUNNING_FILE" || fail "cannot enumerate running containers before quiesce"
  [[ -s "$RUNNING_FILE" ]] || fail "no running containers found before cutover quiesce"
  while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    policy="$(timeout 15s docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$name")" || fail "cannot read restart policy for $name"
    [[ "$policy" == always || "$policy" == unless-stopped ]] || fail "running container lacks reboot-safe restart policy: $name ($policy)"
    pid="$(timeout 15s docker inspect -f '{{.State.Pid}}' "$name")" || fail "cannot read runtime PID for $name"
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || fail "invalid runtime PID for $name: $pid"
    printf '%s|%s\n' "$name" "$pid" >> "$RUNNING_PID_FILE"
  done < "$RUNNING_FILE"

  # Do not call `docker stop`: with `restart: unless-stopped` that would persist
  # manual-stop intent and could keep the production stack down after reboot.
  RUNTIME_STOPPED=1
  log "Stopping Docker daemon without manual container stops to preserve restart eligibility"
  timeout 120s systemctl stop docker.socket || fail "failed to stop docker.socket"
  timeout 120s systemctl stop docker.service || fail "failed to stop docker.service"
  timeout 120s systemctl stop containerd.service || fail "failed to stop containerd.service"
  if systemctl is-active --quiet docker.service || systemctl is-active --quiet docker.socket || systemctl is-active --quiet containerd.service; then
    fail "Docker/containerd remained active after quiesce request"
  fi
  while IFS='|' read -r name pid; do
    [[ -n "$name" && -n "$pid" ]] || continue
    if kill -0 "$pid" 2>/dev/null; then
      fail "container process remained alive after daemon quiesce: $name pid=$pid"
    fi
  done < "$RUNNING_PID_FILE"
  log "Docker/containerd are quiesced and restart eligibility is preserved for final filesystem sync"
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
  validate_pre_cutover_runtime
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
