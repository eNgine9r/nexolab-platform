#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="nexolab-remote-desktop-commander.service"
DESKTOP_COMMANDER_VERSION="0.2.48"
HOME_DIR="${NEXOLAB_REMOTE_ADMIN_HOME:-${HOME}}"
SYSTEMD_USER_DIR="${NEXOLAB_SYSTEMD_USER_DIR:-${HOME_DIR}/.config/systemd/user}"
PACKAGE_ROOT="${NEXOLAB_REMOTE_ADMIN_PACKAGE_ROOT:-${HOME_DIR}/.local/share/nexolab-remote-admin}"
NODE_VERSION="$(tr -d '[:space:]' <"${ROOT_DIR}/.nvmrc")"
NODE_BIN_DIR="${NEXOLAB_NODE_BIN_DIR:-${HOME_DIR}/.nvm/versions/node/v${NODE_VERSION}/bin}"
UNIT_SOURCE="${ROOT_DIR}/infrastructure/systemd/user/${SERVICE_NAME}"
UNIT_TARGET="${SYSTEMD_USER_DIR}/${SERVICE_NAME}"
DRY_RUN=0
SKIP_PACKAGE_INSTALL=0
DEFER_START=0

usage() {
  cat <<'EOF'
Usage: install-raspberry-pi-remote-admin.sh [--dry-run] [--skip-package-install] [--defer-start]

Installs the NEXOLAB Remote Desktop Commander as an independent systemd user service.
Use --defer-start when migrating from a legacy interactive/tmux process so two remote
processes never consume the same persisted device identity concurrently.
Run as the ordinary nexolab user, not as root.
EOF
}
while (($# > 0)); do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --skip-package-install)
      SKIP_PACKAGE_INSTALL=1
      ;;
    --defer-start)
      DEFER_START=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "${UNIT_SOURCE}" ]]; then
  printf 'Missing service template: %s\n' "${UNIT_SOURCE}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" != "1" && "${EUID}" -eq 0 ]]; then
  echo "Run this installer as the ordinary nexolab user, not root." >&2
  exit 1
fi
if [[ "${DRY_RUN}" != "1" && "${HOME_DIR}" != "/home/nexolab" ]]; then
  printf 'Refusing unexpected home directory: %s\n' "${HOME_DIR}" >&2
  exit 1
fi

NODE="${NODE_BIN_DIR}/node"
NPM="${NODE_BIN_DIR}/npm"

if [[ "${DRY_RUN}" == "1" ]]; then
  printf 'dry_run=true\n'
  printf 'desktop_commander_version=%s\n' "${DESKTOP_COMMANDER_VERSION}"
  printf 'package_root=%s\n' "${PACKAGE_ROOT}"
  printf 'unit_source=%s\n' "${UNIT_SOURCE}"
  printf 'unit_target=%s\n' "${UNIT_TARGET}"
  printf 'node=%s\n' "${NODE}"
  printf 'defer_start=%s\n' "${DEFER_START}"
  exit 0
fi

if [[ ! -x "${NODE}" || ! -x "${NPM}" ]]; then
  printf 'Required Node %s toolchain is missing under %s\n' "${NODE_VERSION}" "${NODE_BIN_DIR}" >&2
  exit 1
fi

export PATH="${NODE_BIN_DIR}:/usr/local/bin:/usr/bin:/bin"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
if [[ "$(loginctl show-user "$(id -un)" -p Linger --value)" != "yes" ]]; then
  echo "User linger must be enabled before installing the remote service." >&2
  exit 1
fi

mkdir -p "${PACKAGE_ROOT}" "${SYSTEMD_USER_DIR}"
if [[ "${SKIP_PACKAGE_INSTALL}" != "1" ]]; then
  "${NPM}" install --prefix "${PACKAGE_ROOT}" --no-audit --no-fund --omit=dev --no-save \
    "@wonderwhy-er/desktop-commander@${DESKTOP_COMMANDER_VERSION}"
fi

PACKAGE_JSON="${PACKAGE_ROOT}/node_modules/@wonderwhy-er/desktop-commander/package.json"
if [[ ! -f "${PACKAGE_JSON}" ]]; then
  printf 'Desktop Commander package is missing: %s\n' "${PACKAGE_JSON}" >&2
  exit 1
fi
INSTALLED_VERSION="$("${NODE}" -e 'console.log(require(process.argv[1]).version)' "${PACKAGE_JSON}")"
if [[ "${INSTALLED_VERSION}" != "${DESKTOP_COMMANDER_VERSION}" ]]; then
  printf 'Desktop Commander version mismatch: expected %s, got %s\n' \
    "${DESKTOP_COMMANDER_VERSION}" "${INSTALLED_VERSION}" >&2
  exit 1
fi

install -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
systemctl --user daemon-reload
if [[ "${DEFER_START}" == "1" ]]; then
  systemctl --user enable "${SERVICE_NAME}"
else
  systemctl --user enable --now "${SERVICE_NAME}"
fi
ENABLED="$(systemctl --user is-enabled "${SERVICE_NAME}")"
ACTIVE="$(systemctl --user is-active "${SERVICE_NAME}" || true)"
MAIN_PID="$(systemctl --user show "${SERVICE_NAME}" -p MainPID --value)"
CONTROL_GROUP="$(systemctl --user show "${SERVICE_NAME}" -p ControlGroup --value)"

if [[ "${ENABLED}" != "enabled" ]]; then
  printf 'Remote service enablement failed: enabled=%s\n' "${ENABLED}" >&2
  exit 1
fi
if [[ "${DEFER_START}" != "1" && ( "${ACTIVE}" != "active" || "${MAIN_PID}" == "0" ) ]]; then
  printf 'Remote service verification failed: enabled=%s active=%s pid=%s\n' \
    "${ENABLED}" "${ACTIVE}" "${MAIN_PID}" >&2
  exit 1
fi

printf 'desktop_commander_version=%s\n' "${INSTALLED_VERSION}"
printf 'service_enabled=%s\n' "${ENABLED}"
printf 'service_active=%s\n' "${ACTIVE}"
printf 'service_main_pid=%s\n' "${MAIN_PID}"
printf 'service_control_group=%s\n' "${CONTROL_GROUP}"
printf 'linger=%s\n' "$(loginctl show-user "$(id -un)" -p Linger --value)"
echo "Remote Desktop Commander user service installation completed."
