#!/usr/bin/env bash
set -u

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

section() {
  printf '\n=== %s ===\n' "$1"
}

service_state() {
  local unit="$1"
  printf '%s enabled=' "${unit}"
  systemctl is-enabled "${unit}" 2>/dev/null || printf 'unknown\n'
  printf '%s active=' "${unit}"
  systemctl is-active "${unit}" 2>/dev/null || printf 'unknown\n'
}

user_service_state() {
  local unit="$1"
  printf '%s enabled=' "${unit}"
  systemctl --user is-enabled "${unit}" 2>/dev/null || printf 'unknown\n'
  printf '%s active=' "${unit}"
  systemctl --user is-active "${unit}" 2>/dev/null || printf 'unknown\n'
}
section "HOST"
printf 'timestamp='; date -Is
printf 'hostname='; hostname
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'uptime='; uptime -p
printf 'root='; findmnt -no SOURCE,FSTYPE / 2>/dev/null || true
printf 'boot='; findmnt -no SOURCE,FSTYPE /boot/firmware 2>/dev/null || true
journalctl --list-boots --no-pager 2>/dev/null | tail -5 || true

section "MEMORY AND SWAP"
free -h || true
cat /proc/swaps 2>/dev/null || true
for file in /sys/block/zram0/backing_dev /sys/block/zram0/disksize /sys/block/zram0/mm_stat /sys/block/zram0/bd_stat; do
  if [[ -r "${file}" ]]; then
    printf '%s=' "$(basename "${file}")"
    cat "${file}"
  fi
done

section "POWER THERMAL WATCHDOG"
if command -v vcgencmd >/dev/null 2>&1; then
  vcgencmd get_throttled || true
  vcgencmd measure_temp || true
fi
systemctl show -p RuntimeWatchdogUSec -p RuntimeWatchdogPreUSec 2>/dev/null || true
section "NETWORK AND REMOTE SERVICES"
service_state NetworkManager.service
service_state tailscaled.service
if command -v nmcli >/dev/null 2>&1; then
  printf 'eth0_state='; nmcli -g GENERAL.STATE device show eth0 2>/dev/null || printf 'unavailable\n'
fi
printf 'linger='; loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || printf 'unknown\n'
user_service_state rpi-connect.service
user_service_state rpi-connect-wayvnc.service
user_service_state nexolab-remote-desktop-commander.service

for unit in rpi-connect.service nexolab-remote-desktop-commander.service; do
  printf '%s ' "${unit}"
  systemctl --user show "${unit}" -p MainPID -p ControlGroup -p NRestarts --value 2>/dev/null \
    | paste -sd ' ' - || printf 'details=unavailable\n'
done

section "SSD USB TRANSPORT"
lsusb -t 2>/dev/null || true
journalctl -b -k --no-pager 2>/dev/null \
  | grep -Ei 'uas|usb.*reset|usb disconnect|I/O error|ext4.*error|sda.*error' \
  | tail -60 || true
section "CURRENT BOOT FAILURE SIGNALS"
journalctl -b --no-pager 2>/dev/null \
  | grep -Ei 'watchdog|under.?voltage|oom|out of memory|killed process|thermal|I/O error|ext4.*error|usb.*reset|usb disconnect|hung task|blocked for more than|network is unreachable' \
  | tail -120 || true

section "PREVIOUS BOOT FAILURE SIGNALS"
if journalctl -b -1 -n 1 --no-pager >/dev/null 2>&1; then
  journalctl -b -1 --no-pager 2>/dev/null \
    | grep -Ei 'watchdog|under.?voltage|oom|out of memory|killed process|kernel panic|thermal|I/O error|ext4.*error|uas|usb.*reset|usb disconnect|hung task|blocked for more than|network is unreachable|reboot|shutdown' \
    | tail -160 || true
else
  echo 'previous_boot_journal=unavailable'
fi

section "JOURNAL STORAGE"
systemd-analyze cat-config systemd/journald.conf 2>/dev/null \
  | grep -E '^(Storage|SystemMaxUse|SystemKeepFree|MaxRetentionSec|SyncIntervalSec)=' || true
journalctl --disk-usage 2>/dev/null || true

section "BOUNDARY"
echo 'modbus_write=none'
echo 'hardware_write=none'
echo 'production_application_mutation=none'
