#!/usr/bin/env bash
set -uo pipefail

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

MIN_MEM_AVAILABLE_KIB="${NEXOLAB_STABILITY_MIN_MEM_AVAILABLE_KIB:-1048576}"
MIN_SWAP_FREE_KIB="${NEXOLAB_STABILITY_MIN_SWAP_FREE_KIB:-524288}"
MIN_ROOT_FREE_PERCENT="${NEXOLAB_STABILITY_MIN_ROOT_FREE_PERCENT:-10}"
MANAGED_REMOTE_UNIT="nexolab-remote-desktop-commander.service"
AUX_UNITS=(nexolab-browser.service nexolab-opera-inspection.service)
REQUIRED_RUNTIME_CONTAINERS=(
  nexolab-central-alertmanager-1
  nexolab-central-grafana-1
  nexolab-central-minio-1
  nexolab-central-mqtt-1
  nexolab-central-observability-alert-sink-1
  nexolab-central-observability-textfile-1
  nexolab-central-postgres-1
  nexolab-central-prometheus-1
  nexolab-central-telegram-gateway-1
  nexolab-central-telemetry-service-1
  nexolab-edge-device-agent-1
  nexolab-edge-mqtt-1
)
COMMAND_TIMEOUT_SECONDS="${NEXOLAB_STABILITY_COMMAND_TIMEOUT_SECONDS:-5}"
FAILURES=0

fail() { printf 'FAIL %s\n' "$*"; FAILURES=$((FAILURES + 1)); }
pass() { printf 'PASS %s\n' "$*"; }
info() { printf 'INFO %s\n' "$*"; }

MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
if [[ "${MODEL}" != *"Raspberry Pi"* && "${NEXOLAB_HOST_STABILITY_ALLOW_NON_RPI:-0}" != "1" ]]; then
  fail "host_identity model=${MODEL:-unknown}"
else
  pass "host_identity model=${MODEL:-override}"
fi

MEM_AVAILABLE_KIB="$(awk '$1 == "MemAvailable:" {print $2; exit}' /proc/meminfo)"
SWAP_FREE_KIB="$(awk '$1 == "SwapFree:" {print $2; exit}' /proc/meminfo)"
info "memory mem_available_kib=${MEM_AVAILABLE_KIB:-unknown} min=${MIN_MEM_AVAILABLE_KIB} swap_free_kib=${SWAP_FREE_KIB:-unknown} min_swap=${MIN_SWAP_FREE_KIB}"
[[ "${MEM_AVAILABLE_KIB:-0}" =~ ^[0-9]+$ && "${MEM_AVAILABLE_KIB}" -ge "${MIN_MEM_AVAILABLE_KIB}" ]] \
  && pass "memory_headroom" || fail "memory_headroom"
[[ "${SWAP_FREE_KIB:-0}" =~ ^[0-9]+$ && "${SWAP_FREE_KIB}" -ge "${MIN_SWAP_FREE_KIB}" ]] \
  && pass "swap_headroom" || fail "swap_headroom"

ROOT_USE_PERCENT="$(df -P / | awk 'NR==2 {gsub(/%/, "", $5); print $5}')"
ROOT_FREE_PERCENT=$((100 - ${ROOT_USE_PERCENT:-100}))
info "root_disk free_percent=${ROOT_FREE_PERCENT} min=${MIN_ROOT_FREE_PERCENT}"
(( ROOT_FREE_PERCENT >= MIN_ROOT_FREE_PERCENT )) && pass "root_disk_headroom" || fail "root_disk_headroom"

if command -v vcgencmd >/dev/null 2>&1; then
  THROTTLED="$(vcgencmd get_throttled 2>/dev/null || true)"
  TEMP="$(vcgencmd measure_temp 2>/dev/null || true)"
  info "thermal ${THROTTLED:-unavailable} ${TEMP:-unavailable}"
  [[ "${THROTTLED}" == "throttled=0x0" ]] && pass "power_thermal" || fail "power_thermal"
else
  info "thermal vcgencmd_unavailable"
fi

WATCHDOG="$(systemctl show -p RuntimeWatchdogUSec --value 2>/dev/null || true)"
info "watchdog runtime=${WATCHDOG:-unavailable}"

ETH_STATE="$(cat /sys/class/net/eth0/operstate 2>/dev/null || true)"
RX_ERRORS="$(cat /sys/class/net/eth0/statistics/rx_errors 2>/dev/null || echo 0)"
TX_ERRORS="$(cat /sys/class/net/eth0/statistics/tx_errors 2>/dev/null || echo 0)"
info "network eth0_state=${ETH_STATE:-unknown} rx_errors=${RX_ERRORS} tx_errors=${TX_ERRORS}"
[[ "${ETH_STATE}" == "up" && "${RX_ERRORS}" == "0" && "${TX_ERRORS}" == "0" ]] \
  && pass "eth0_link" || fail "eth0_link"

systemctl is-active --quiet tailscaled.service && pass "tailscaled_active" || fail "tailscaled_active"
systemctl --user is-enabled --quiet "${MANAGED_REMOTE_UNIT}" && pass "remote_admin_enabled" || fail "remote_admin_enabled"
systemctl --user is-active --quiet "${MANAGED_REMOTE_UNIT}" && pass "remote_admin_active" || fail "remote_admin_active"

for unit in "${AUX_UNITS[@]}"; do
  enabled="$(systemctl --user is-enabled "${unit}" 2>/dev/null || true)"
  active="$(systemctl --user is-active "${unit}" 2>/dev/null || true)"
  info "auxiliary unit=${unit} enabled=${enabled:-unknown} active=${active:-unknown}"
  [[ "${enabled}" != "enabled" && "${active}" != "active" ]] \
    && pass "auxiliary_on_demand unit=${unit}" || fail "auxiliary_on_demand unit=${unit}"
done

UNMANAGED_REMOTE=0
while read -r pid; do
  [[ -n "${pid}" ]] || continue
  cgroup="$(cat "/proc/${pid}/cgroup" 2>/dev/null || true)"
  [[ "${cgroup}" == *"/${MANAGED_REMOTE_UNIT}" ]] || UNMANAGED_REMOTE=$((UNMANAGED_REMOTE + 1))
done < <(pgrep -f '[d]esktop-commander' 2>/dev/null || true)
info "remote_admin unmanaged_processes=${UNMANAGED_REMOTE}"
(( UNMANAGED_REMOTE == 0 )) && pass "single_remote_admin_owner" || fail "single_remote_admin_owner"

if tmux has-session -t remote-desktop 2>/dev/null; then
  fail "legacy_remote_desktop_tmux_absent"
else
  pass "legacy_remote_desktop_tmux_absent"
fi
if grep -qw 'cgroup_disable=memory' /proc/cmdline 2>/dev/null; then
  info "memory_cgroup=disabled"
else
  info "memory_cgroup=enabled_or_unspecified"
fi

if command -v docker >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
  runtime_failures=0
  for container in "${REQUIRED_RUNTIME_CONTAINERS[@]}"; do
    state="$(timeout --foreground "${COMMAND_TIMEOUT_SECONDS}s" docker inspect -f '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}missing-healthcheck{{end}}' "${container}" 2>/dev/null || true)"
    info "runtime container=${container} state=${state:-unavailable}"
    if [[ "${state}" != "running|healthy" ]]; then
      runtime_failures=$((runtime_failures + 1))
    fi
  done
  info "runtime required=${#REQUIRED_RUNTIME_CONTAINERS[@]} failures=${runtime_failures}"
  (( runtime_failures == 0 )) && pass "nexolab_runtime_containers" || fail "nexolab_runtime_containers"
else
  fail "docker_and_timeout_commands_available"
fi

if [[ -r /proc/pressure/memory ]]; then
  info "memory_pressure $(tr '\n' ';' </proc/pressure/memory)"
else
  info "memory_pressure=unavailable"
fi
if [[ -r /proc/pressure/io ]]; then
  info "io_pressure $(tr '\n' ';' </proc/pressure/io)"
else
  info "io_pressure=unavailable"
fi

echo 'modbus_write=none'
echo 'hardware_write=none'
echo 'production_data_mutation=none'
if (( FAILURES == 0 )); then
  echo 'result=PASS'
  exit 0
fi
printf 'result=FAIL failures=%d\n' "${FAILURES}"
exit 1
