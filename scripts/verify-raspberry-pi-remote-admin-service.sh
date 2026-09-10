#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="nexolab-remote-desktop-commander.service"
SOURCE_CONFIG="${ROOT_DIR}/infrastructure/remote-admin/desktop-commander-source.env"
HOME_DIR="${NEXOLAB_REMOTE_ADMIN_HOME:-${HOME}}"
SYSTEMD_USER_DIR="${NEXOLAB_SYSTEMD_USER_DIR:-${HOME_DIR}/.config/systemd/user}"
PACKAGE_BASE="${NEXOLAB_REMOTE_ADMIN_PACKAGE_ROOT:-${HOME_DIR}/.local/share/nexolab-remote-admin}"
NODE_VERSION="$(tr -d '[:space:]' <"${ROOT_DIR}/.nvmrc")"
NODE="${NEXOLAB_NODE_BIN_DIR:-${HOME_DIR}/.nvm/versions/node/v${NODE_VERSION}/bin}/node"
UNIT_TARGET="${SYSTEMD_USER_DIR}/${SERVICE_NAME}"
RESTART=0
POLICY_ONLY=0
STATE_FILE=""

usage() {
  cat <<'USAGE'
Usage: verify-raspberry-pi-remote-admin-service.sh [--policy-only] [--restart] [--state-file PATH]

Verifies pinned package provenance plus the effective NEXOLAB Remote Desktop Commander
user-service policy. --restart is allowed only outside the managed service cgroup.
USAGE
}

while (($# > 0)); do
  case "$1" in
    --policy-only) POLICY_ONLY=1 ;;
    --restart) RESTART=1 ;;
    --state-file) shift; [[ $# -gt 0 ]] || { echo 'Missing --state-file value.' >&2; exit 2; }; STATE_FILE="$1" ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[[ "${RESTART}" == "1" && "${POLICY_ONLY}" == "1" ]] && { echo 'Choose either --policy-only or --restart, not both.' >&2; exit 2; }
[[ "${EUID}" -ne 0 ]] || { echo 'Run as the ordinary NEXOLAB user, not root.' >&2; exit 1; }
[[ -f "${SOURCE_CONFIG}" ]] || { printf 'Missing source pin: %s\n' "${SOURCE_CONFIG}" >&2; exit 1; }
# shellcheck disable=SC1090
source "${SOURCE_CONFIG}"

EXPECTED_RELEASE="${PACKAGE_BASE}/releases/${DESKTOP_COMMANDER_SOURCE_SHA}"
CURRENT_ROOT="${PACKAGE_BASE}/current"
PACKAGE_JSON="${CURRENT_ROOT}/node_modules/@wonderwhy-er/desktop-commander/package.json"
ENTRYPOINT="${CURRENT_ROOT}/node_modules/@wonderwhy-er/desktop-commander/dist/index.js"
DEVICE_JS="${CURRENT_ROOT}/node_modules/@wonderwhy-er/desktop-commander/dist/remote-device/device.js"
CHANNEL_JS="${CURRENT_ROOT}/node_modules/@wonderwhy-er/desktop-commander/dist/remote-device/remote-channel.js"
PROVENANCE_FILE="${CURRENT_ROOT}/NEXOLAB_SOURCE.env"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

property() { systemctl --user show "${SERVICE_NAME}" -p "$1" --value; }

write_state() {
  local rc=$?
  trap - EXIT
  if [[ -n "${STATE_FILE}" ]]; then
    umask 077
    mkdir -p "$(dirname -- "${STATE_FILE}")"
    {
      printf 'timestamp=%s\nservice=%s\nsource_sha=%s\n' "$(date -Is)" "${SERVICE_NAME}" "${DESKTOP_COMMANDER_SOURCE_SHA}"
      if ((rc == 0)); then printf 'status=success\n'; else printf 'status=failure\n'; fi
      printf 'exit_code=%s\n' "${rc}"
      printf 'main_pid=%s\n' "$(property MainPID 2>/dev/null || printf 'unknown')"
    } >"${STATE_FILE}"
  fi
  exit "${rc}"
}
trap write_state EXIT

verify_source() {
  local resolved version
  resolved="$(readlink -f "${CURRENT_ROOT}" 2>/dev/null || true)"
  [[ "${resolved}" == "${EXPECTED_RELEASE}" ]] || { printf 'Unexpected current release: %s\n' "${resolved:-missing}" >&2; return 1; }
  for required in "${PACKAGE_JSON}" "${ENTRYPOINT}" "${DEVICE_JS}" "${CHANNEL_JS}" "${PROVENANCE_FILE}"; do
    [[ -f "${required}" ]] || { printf 'Pinned release file missing: %s\n' "${required}" >&2; return 1; }
  done
  version="$("${NODE}" -e 'console.log(require(process.argv[1]).version)' "${PACKAGE_JSON}")"
  [[ "${version}" == "${DESKTOP_COMMANDER_VERSION}" ]] || { printf 'Unexpected package version: %s\n' "${version}" >&2; return 1; }
  grep -Fxq "source_repo=${DESKTOP_COMMANDER_SOURCE_REPO}" "${PROVENANCE_FILE}" || { echo 'Source repository provenance mismatch.' >&2; return 1; }
  grep -Fxq "source_sha=${DESKTOP_COMMANDER_SOURCE_SHA}" "${PROVENANCE_FILE}" || { echo 'Source SHA provenance mismatch.' >&2; return 1; }
  grep -Fq 'onSessionRotated' "${DEVICE_JS}" || { echo 'Rotated-session persistence missing from device runtime.' >&2; return 1; }
  grep -Fq 'onSessionRotated' "${CHANNEL_JS}" || { echo 'Rotated-session observer missing from channel runtime.' >&2; return 1; }
  grep -Fq 'writePersistedConfigSnapshot' "${DEVICE_JS}" || { echo 'Atomic session persistence missing from device runtime.' >&2; return 1; }
}

verify_policy() {
  local fragment dropins restart_policy stdout_policy stderr_policy kill_mode exec_start
  fragment="$(property FragmentPath)"
  dropins="$(property DropInPaths)"
  restart_policy="$(property Restart)"
  stdout_policy="$(property StandardOutput)"
  stderr_policy="$(property StandardError)"
  kill_mode="$(property KillMode)"
  exec_start="$(property ExecStart)"
  [[ "${fragment}" == "${UNIT_TARGET}" ]] || { printf 'Unexpected FragmentPath: %s\n' "${fragment}" >&2; return 1; }
  [[ -z "${dropins}" ]] || { printf 'Refusing effective service drop-ins: %s\n' "${dropins}" >&2; return 1; }
  [[ "${restart_policy}" == "always" ]] || { printf 'Unexpected Restart policy: %s\n' "${restart_policy}" >&2; return 1; }
  [[ "${stdout_policy}" == "null" ]] || { printf 'Unexpected StandardOutput policy: %s\n' "${stdout_policy}" >&2; return 1; }
  [[ "${stderr_policy}" == "journal" ]] || { printf 'Unexpected StandardError policy: %s\n' "${stderr_policy}" >&2; return 1; }
  [[ "${kill_mode}" == "mixed" ]] || { printf 'Unexpected KillMode: %s\n' "${kill_mode}" >&2; return 1; }
  [[ "${exec_start}" == *"path=${NODE}"* ]] || { printf 'Unexpected ExecStart node path: %s\n' "${exec_start}" >&2; return 1; }
  [[ "${exec_start}" == *"${ENTRYPOINT} remote"* ]] || { printf 'Unexpected ExecStart entrypoint: %s\n' "${exec_start}" >&2; return 1; }
  [[ "${exec_start}" != *"npx"* && "${exec_start}" != *"@latest"* ]] || { printf 'Unpinned ExecStart rejected: %s\n' "${exec_start}" >&2; return 1; }
}

verify_source
verify_policy
ENABLED="$(systemctl --user is-enabled "${SERVICE_NAME}")"
[[ "${ENABLED}" == "enabled" ]] || { printf 'Service is not enabled: %s\n' "${ENABLED}" >&2; exit 1; }

if [[ "${RESTART}" == "1" ]]; then
  grep -Fq "/${SERVICE_NAME}" "/proc/$$/cgroup" 2>/dev/null && { echo 'Refusing to restart the managed service from inside its own cgroup.' >&2; exit 1; }
  BEFORE_RESTARTS="$(property NRestarts)"
  systemctl --user restart "${SERVICE_NAME}"
  sleep 5
  ACTIVE_A="$(systemctl --user is-active "${SERVICE_NAME}" || true)"
  PID_A="$(property MainPID)"
  RESTARTS_A="$(property NRestarts)"
  sleep 12
  ACTIVE_B="$(systemctl --user is-active "${SERVICE_NAME}" || true)"
  PID_B="$(property MainPID)"
  RESTARTS_B="$(property NRestarts)"
  [[ "${ACTIVE_A}" == "active" && "${ACTIVE_B}" == "active" && "${PID_A}" != "0" && "${PID_A}" == "${PID_B}" ]] || {
    printf 'Service did not remain stable after restart: active=%s/%s pid=%s/%s\n' "${ACTIVE_A}" "${ACTIVE_B}" "${PID_A}" "${PID_B}" >&2; exit 1;
  }
  [[ "${RESTARTS_A}" == "${BEFORE_RESTARTS}" && "${RESTARTS_B}" == "${BEFORE_RESTARTS}" ]] || {
    printf 'Service restarted unexpectedly during stabilization: before=%s after=%s/%s\n' "${BEFORE_RESTARTS}" "${RESTARTS_A}" "${RESTARTS_B}" >&2; exit 1;
  }
  verify_source
  verify_policy
fi

if [[ "${POLICY_ONLY}" != "1" ]]; then
  ACTIVE="$(systemctl --user is-active "${SERVICE_NAME}" || true)"
  MAIN_PID="$(property MainPID)"
  [[ "${ACTIVE}" == "active" && "${MAIN_PID}" != "0" ]] || { printf 'Service runtime verification failed: active=%s pid=%s\n' "${ACTIVE}" "${MAIN_PID}" >&2; exit 1; }
  printf 'service_active=%s\nservice_main_pid=%s\n' "${ACTIVE}" "${MAIN_PID}"
fi

printf 'service_enabled=%s\nsource_sha=%s\neffective_release=%s\n' "${ENABLED}" "${DESKTOP_COMMANDER_SOURCE_SHA}" "$(readlink -f "${CURRENT_ROOT}")"
printf 'effective_fragment=%s\neffective_restart=%s\neffective_standard_output=%s\neffective_standard_error=%s\neffective_dropins=none\n' \
  "$(property FragmentPath)" "$(property Restart)" "$(property StandardOutput)" "$(property StandardError)"
