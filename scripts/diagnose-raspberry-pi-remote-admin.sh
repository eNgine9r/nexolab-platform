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

journal_probe_access() {
  local output rc=0
  if output="$(journalctl "$@" -n 1 --no-pager 2>&1)"; then
    rc=0
  else
    rc=$?
  fi
  if ((rc != 0)) || grep -Eqi 'insufficient permissions|permission denied|not seeing messages from other users|No journal files were opened' <<<"${output}"; then
    return 1
  fi
  [[ -n "${output}" ]] && ! grep -qx -- '-- No entries --' <<<"${output}"
}

SYSTEM_JOURNAL_ACCESS=unavailable
KERNEL_JOURNAL_ACCESS=unavailable
if journal_probe_access -b _UID=0; then
  SYSTEM_JOURNAL_ACCESS=available
fi
if journal_probe_access -b -k; then
  KERNEL_JOURNAL_ACCESS=available
fi

section "HOST"
printf 'timestamp='; date -Is
printf 'hostname='; hostname
printf 'boot_id='; cat /proc/sys/kernel/random/boot_id
printf 'uptime='; uptime -p
printf 'root='; findmnt -no SOURCE,FSTYPE / 2>/dev/null || true
printf 'boot='; findmnt -no SOURCE,FSTYPE /boot/firmware 2>/dev/null || true
printf 'system_journal_access=%s\n' "${SYSTEM_JOURNAL_ACCESS}"
printf 'kernel_journal_access=%s\n' "${KERNEL_JOURNAL_ACCESS}"
if [[ "${SYSTEM_JOURNAL_ACCESS}" == "available" ]]; then
  journalctl --list-boots --no-pager 2>/dev/null | tail -5 || true
else
  echo 'journal_boot_list=unavailable'
fi

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
if command -v tailscale >/dev/null 2>&1; then
  if TAILSCALE_STATUS="$(tailscale status --json 2>/dev/null)"; then
    python3 -c 'import json,sys; d=json.load(sys.stdin); s=d.get("Self") or {}; print("tailscale_backend_state=" + str(d.get("BackendState", "unknown"))); print("tailscale_self_online=" + str(bool(s.get("Online"))).lower()); print("tailscale_ips=" + ",".join(d.get("TailscaleIPs") or []))' <<<"${TAILSCALE_STATUS}" || echo 'tailscale_connectivity=unparseable'
  else
    echo 'tailscale_connectivity=unavailable'
  fi
else
  echo 'tailscale_connectivity=command_missing'
fi
if command -v nmcli >/dev/null 2>&1; then
  printf 'eth0_state='; nmcli -g GENERAL.STATE device show eth0 2>/dev/null || printf 'unavailable\n'
fi
printf 'linger='; loginctl show-user "$(id -un)" -p Linger --value 2>/dev/null || printf 'unknown\n'
user_service_state rpi-connect.service
if command -v rpi-connect >/dev/null 2>&1; then
  if RPI_CONNECT_STATUS="$(rpi-connect status 2>&1)"; then
    RPI_CONNECT_STATUS_RC=0
  else
    RPI_CONNECT_STATUS_RC=$?
  fi
  printf 'rpi_connect_status_rc=%s\n' "${RPI_CONNECT_STATUS_RC}"
  while IFS= read -r line; do
    printf 'rpi_connect_status=%s\n' "${line}"
  done <<<"${RPI_CONNECT_STATUS}"
else
  echo 'rpi_connect_status=command_missing'
fi
user_service_state rpi-connect-wayvnc.service
user_service_state nexolab-remote-desktop-commander.service

for unit in rpi-connect.service nexolab-remote-desktop-commander.service; do
  printf '%s ' "${unit}"
  systemctl --user show "${unit}" -p MainPID -p ControlGroup -p NRestarts --value 2>/dev/null \
    | paste -sd ' ' - || printf 'details=unavailable\n'
done

section "SSD USB TRANSPORT"
lsusb -t 2>/dev/null || true
if [[ "${KERNEL_JOURNAL_ACCESS}" == "available" ]]; then
  journalctl -b -k --no-pager 2>/dev/null \
    | grep -Ei 'uas|usb.*reset|usb disconnect|I/O error|ext4.*error|sda.*error' \
    | tail -60 || true
else
  echo 'ssd_kernel_journal=unavailable'
fi

section "CURRENT BOOT FAILURE SIGNALS"
if [[ "${SYSTEM_JOURNAL_ACCESS}" == "available" && "${KERNEL_JOURNAL_ACCESS}" == "available" ]]; then
  journalctl -b --no-pager 2>/dev/null \
    _TRANSPORT=kernel \
    + SYSLOG_IDENTIFIER=systemd \
    + SYSLOG_IDENTIFIER=systemd-shutdown \
    + SYSLOG_IDENTIFIER=systemd-oomd \
    + SYSLOG_IDENTIFIER=NetworkManager \
    + SYSLOG_IDENTIFIER=tailscaled \
    + SYSLOG_IDENTIFIER=rpi-connect \
    | grep -Ei 'watchdog|under.?voltage|oom|out of memory|killed process|thermal|I/O error|ext4.*error|usb.*reset|usb disconnect|hung task|blocked for more than|network is unreachable' \
    | tail -120 || true
else
  echo 'current_boot_failure_signals=unavailable'
  printf 'current_boot_system_journal_access=%s\n' "${SYSTEM_JOURNAL_ACCESS}"
  printf 'current_boot_kernel_journal_access=%s\n' "${KERNEL_JOURNAL_ACCESS}"
fi

section "PREVIOUS BOOT FAILURE SIGNALS"
if [[ "${SYSTEM_JOURNAL_ACCESS}" != "available" || "${KERNEL_JOURNAL_ACCESS}" != "available" ]]; then
  echo 'previous_boot_failure_signals=unavailable'
  printf 'previous_boot_system_journal_access=%s\n' "${SYSTEM_JOURNAL_ACCESS}"
  printf 'previous_boot_kernel_journal_access=%s\n' "${KERNEL_JOURNAL_ACCESS}"
elif journalctl -b -1 -n 1 --no-pager >/dev/null 2>&1; then
  journalctl -b -1 --no-pager 2>/dev/null \
    _TRANSPORT=kernel \
    + SYSLOG_IDENTIFIER=systemd \
    + SYSLOG_IDENTIFIER=systemd-shutdown \
    + SYSLOG_IDENTIFIER=systemd-oomd \
    + SYSLOG_IDENTIFIER=NetworkManager \
    + SYSLOG_IDENTIFIER=tailscaled \
    + SYSLOG_IDENTIFIER=rpi-connect \
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
