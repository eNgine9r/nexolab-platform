#!/usr/bin/env bash
set -euo pipefail

MODE="check"
case "${1:-}" in
  ""|--check) MODE="check" ;;
  --dry-run) MODE="dry-run" ;;
  --apply) MODE="apply" ;;
  *) echo "Usage: $0 [--check|--dry-run|--apply]" >&2; exit 64 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFY="${ROOT}/scripts/verify-raspberry-pi-host-stability.sh"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

AUX_UNITS=(nexolab-browser.service nexolab-opera-inspection.service)
MANAGED_REMOTE_UNIT="nexolab-remote-desktop-commander.service"
LEGACY_TMUX="remote-desktop"

if [[ "${MODE}" == "check" ]]; then
  exec "${VERIFY}"
fi

printf 'mode=%s\n' "${MODE}"
printf 'managed_remote_unit=%s\n' "${MANAGED_REMOTE_UNIT}"
printf 'auxiliary_units=%s\n' "${AUX_UNITS[*]}"
printf 'legacy_tmux=%s\n' "${LEGACY_TMUX}"
if [[ "${MODE}" == "dry-run" ]]; then
  for unit in "${AUX_UNITS[@]}"; do
    echo "would_disable_and_stop=${unit}"
  done
  echo "would_remove_legacy_tmux=${LEGACY_TMUX}"
  echo "would_enable_and_start=${MANAGED_REMOTE_UNIT}"
  echo 'modbus_write=none'
  echo 'hardware_write=none'
  echo 'production_runtime_mutation=none'
  exit 0
fi

for unit in "${AUX_UNITS[@]}"; do
  if systemctl --user cat "${unit}" >/dev/null 2>&1; then
    systemctl --user disable --now "${unit}"
  fi
done

if tmux has-session -t "${LEGACY_TMUX}" 2>/dev/null; then
  tmux kill-session -t "${LEGACY_TMUX}"
fi

systemctl --user enable --now "${MANAGED_REMOTE_UNIT}"
sleep 2
exec "${VERIFY}"
