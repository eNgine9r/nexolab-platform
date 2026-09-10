#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_NAME="nexolab-remote-desktop-commander.service"
SOURCE_CONFIG="${ROOT_DIR}/infrastructure/remote-admin/desktop-commander-source.env"
HOME_DIR="${NEXOLAB_REMOTE_ADMIN_HOME:-${HOME}}"
SYSTEMD_USER_DIR="${NEXOLAB_SYSTEMD_USER_DIR:-${HOME_DIR}/.config/systemd/user}"
PACKAGE_BASE="${NEXOLAB_REMOTE_ADMIN_PACKAGE_ROOT:-${HOME_DIR}/.local/share/nexolab-remote-admin}"
NODE_VERSION="$(tr -d '[:space:]' <"${ROOT_DIR}/.nvmrc")"
NODE_BIN_DIR="${NEXOLAB_NODE_BIN_DIR:-${HOME_DIR}/.nvm/versions/node/v${NODE_VERSION}/bin}"
UNIT_SOURCE="${ROOT_DIR}/infrastructure/systemd/user/${SERVICE_NAME}"
UNIT_TARGET="${SYSTEMD_USER_DIR}/${SERVICE_NAME}"
VERIFIER="${ROOT_DIR}/scripts/verify-raspberry-pi-remote-admin-service.sh"
HANDOFF_STATE_DIR="${HOME_DIR}/.local/state/nexolab-remote-admin"
HANDOFF_STATE_FILE="${HANDOFF_STATE_DIR}/last-handoff.env"
DRY_RUN=0
SKIP_PACKAGE_INSTALL=0
DEFER_START=0

usage() {
  cat <<'EOF'
Usage: install-raspberry-pi-remote-admin.sh [--dry-run] [--skip-package-install] [--defer-start]

Installs the NEXOLAB Remote Desktop Commander as an independent systemd user service.
The remote package is pinned to an exact upstream source commit and installed into an
immutable release directory; `current` is switched atomically only after verification.
Use --defer-start while migrating from a legacy interactive process.
Run as the ordinary nexolab user, not as root.
EOF
}

while (($# > 0)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --skip-package-install) SKIP_PACKAGE_INSTALL=1 ;;
    --defer-start) DEFER_START=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for required in "${SOURCE_CONFIG}" "${UNIT_SOURCE}" "${VERIFIER}"; do
  [[ -f "${required}" ]] || { printf 'Missing required file: %s\n' "${required}" >&2; exit 1; }
done
[[ -x "${VERIFIER}" ]] || { printf 'Missing executable service verifier: %s\n' "${VERIFIER}" >&2; exit 1; }
# shellcheck disable=SC1090
source "${SOURCE_CONFIG}"
[[ "${DESKTOP_COMMANDER_SOURCE_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo 'Desktop Commander source SHA must be a full 40-char commit.' >&2; exit 1; }
[[ "${DESKTOP_COMMANDER_SOURCE_REPO}" == https://github.com/*/*.git ]] || { echo 'Desktop Commander source repo must be an HTTPS GitHub .git URL.' >&2; exit 1; }

RELEASES_DIR="${PACKAGE_BASE}/releases"
RELEASE_DIR="${RELEASES_DIR}/${DESKTOP_COMMANDER_SOURCE_SHA}"
CURRENT_LINK="${PACKAGE_BASE}/current"
PACKAGE_SPEC="git+${DESKTOP_COMMANDER_SOURCE_REPO}#${DESKTOP_COMMANDER_SOURCE_SHA}"
NODE="${NODE_BIN_DIR}/node"
NPM="${NODE_BIN_DIR}/npm"

if [[ "${DRY_RUN}" == "1" ]]; then
  printf 'dry_run=true\n'
  printf 'desktop_commander_version=%s\n' "${DESKTOP_COMMANDER_VERSION}"
  printf 'desktop_commander_source_repo=%s\n' "${DESKTOP_COMMANDER_SOURCE_REPO}"
  printf 'desktop_commander_source_sha=%s\n' "${DESKTOP_COMMANDER_SOURCE_SHA}"
  printf 'release_dir=%s\ncurrent_link=%s\nnode=%s\ndefer_start=%s\n' \
    "${RELEASE_DIR}" "${CURRENT_LINK}" "${NODE}" "${DEFER_START}"
  exit 0
fi

[[ "${EUID}" -ne 0 ]] || { echo 'Run this installer as the ordinary nexolab user, not root.' >&2; exit 1; }
[[ "${HOME_DIR}" == "/home/nexolab" ]] || { printf 'Refusing unexpected home directory: %s\n' "${HOME_DIR}" >&2; exit 1; }
[[ -x "${NODE}" && -x "${NPM}" ]] || { printf 'Required Node %s toolchain is missing under %s\n' "${NODE_VERSION}" "${NODE_BIN_DIR}" >&2; exit 1; }

export PATH="${NODE_BIN_DIR}:/usr/local/bin:/usr/bin:/bin"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
[[ "$(loginctl show-user "$(id -un)" -p Linger --value)" == "yes" ]] || { echo 'User linger must be enabled before installing the remote service.' >&2; exit 1; }
if [[ "${DEFER_START}" == "1" ]] && systemctl --user is-active --quiet "${SERVICE_NAME}"; then
  echo 'Refusing --defer-start while the managed service is already active.' >&2
  exit 1
fi

verify_release() {
  local release_path="${1:-${RELEASE_DIR}}"
  local provenance_file="${release_path}/NEXOLAB_SOURCE.env"
  local package_json="${release_path}/node_modules/@wonderwhy-er/desktop-commander/package.json"
  local device_js="${release_path}/node_modules/@wonderwhy-er/desktop-commander/dist/remote-device/device.js"
  local channel_js="${release_path}/node_modules/@wonderwhy-er/desktop-commander/dist/remote-device/remote-channel.js"
  local installed_version
  [[ -f "${package_json}" && -f "${provenance_file}" && -f "${device_js}" && -f "${channel_js}" ]] || return 1
  installed_version="$("${NODE}" -e 'console.log(require(process.argv[1]).version)' "${package_json}")"
  [[ "${installed_version}" == "${DESKTOP_COMMANDER_VERSION}" ]] || return 1
  grep -Fxq "source_repo=${DESKTOP_COMMANDER_SOURCE_REPO}" "${provenance_file}" || return 1
  grep -Fxq "source_sha=${DESKTOP_COMMANDER_SOURCE_SHA}" "${provenance_file}" || return 1
  grep -Fq 'onSessionRotated' "${device_js}" || return 1
  grep -Fq 'onSessionRotated' "${channel_js}" || return 1
  grep -Fq 'writePersistedConfigSnapshot' "${device_js}" || return 1
}

mkdir -p "${RELEASES_DIR}" "${SYSTEMD_USER_DIR}"
if [[ -e "${RELEASE_DIR}" ]]; then
  verify_release || { printf 'Existing immutable release failed verification; refusing mutation: %s\n' "${RELEASE_DIR}" >&2; exit 1; }
elif [[ "${SKIP_PACKAGE_INSTALL}" == "1" ]]; then
  printf 'Pinned release is missing: %s\n' "${RELEASE_DIR}" >&2
  exit 1
else
  STAGING_DIR="${RELEASE_DIR}.staging.$$"
  trap 'rm -rf -- "${STAGING_DIR:-}"' EXIT
  rm -rf -- "${STAGING_DIR}"
  mkdir -p "${STAGING_DIR}"
  "${NPM}" install --prefix "${STAGING_DIR}" --no-audit --no-fund --omit=dev --no-save "${PACKAGE_SPEC}"
  {
    printf 'version=%s\n' "${DESKTOP_COMMANDER_VERSION}"
    printf 'source_repo=%s\n' "${DESKTOP_COMMANDER_SOURCE_REPO}"
    printf 'source_sha=%s\n' "${DESKTOP_COMMANDER_SOURCE_SHA}"
  } >"${STAGING_DIR}/NEXOLAB_SOURCE.env"
  chmod 0644 "${STAGING_DIR}/NEXOLAB_SOURCE.env"
  verify_release "${STAGING_DIR}" || { echo 'Staged pinned Desktop Commander release failed verification.' >&2; exit 1; }
  mv -- "${STAGING_DIR}" "${RELEASE_DIR}"
  trap - EXIT
  verify_release "${RELEASE_DIR}" || { echo 'Installed pinned Desktop Commander release failed post-promotion verification.' >&2; exit 1; }
fi

CURRENT_TMP="${PACKAGE_BASE}/.current.$$"
rm -f -- "${CURRENT_TMP}"
ln -s "releases/${DESKTOP_COMMANDER_SOURCE_SHA}" "${CURRENT_TMP}"
mv -Tf -- "${CURRENT_TMP}" "${CURRENT_LINK}"
[[ "$(readlink -f "${CURRENT_LINK}")" == "${RELEASE_DIR}" ]] || { echo 'Atomic current-link switch failed.' >&2; exit 1; }

install -m 0644 "${UNIT_SOURCE}" "${UNIT_TARGET}"
systemctl --user daemon-reload
systemctl --user enable "${SERVICE_NAME}"
"${VERIFIER}" --policy-only

if [[ "${DEFER_START}" == "1" ]]; then
  printf 'desktop_commander_version=%s\ndesktop_commander_source_sha=%s\nservice_restart=deferred\nlinger=%s\n' \
    "${DESKTOP_COMMANDER_VERSION}" "${DESKTOP_COMMANDER_SOURCE_SHA}" "$(loginctl show-user "$(id -un)" -p Linger --value)"
  echo 'Remote Desktop Commander release staged without restart.'
  exit 0
fi

if grep -Fq "/${SERVICE_NAME}" "/proc/$$/cgroup" 2>/dev/null; then
  command -v systemd-run >/dev/null 2>&1 || { echo 'systemd-run is required for a safe self-update restart handoff.' >&2; exit 1; }
  mkdir -p "${HANDOFF_STATE_DIR}"
  chmod 0700 "${HANDOFF_STATE_DIR}"
  rm -f "${HANDOFF_STATE_FILE}"
  HANDOFF_UNIT="nexolab-remote-admin-handoff-$(date +%s)-$$"
  systemd-run --user --quiet --collect --unit="${HANDOFF_UNIT}" \
    /bin/bash -c 'sleep 2; exec "$1" --restart --state-file "$2"' \
    _ "${VERIFIER}" "${HANDOFF_STATE_FILE}"
  printf 'desktop_commander_version=%s\ndesktop_commander_source_sha=%s\nservice_restart_handoff=scheduled\n' \
    "${DESKTOP_COMMANDER_VERSION}" "${DESKTOP_COMMANDER_SOURCE_SHA}"
  printf 'service_restart_handoff_unit=%s\nservice_restart_handoff_state=%s\nlinger=%s\n' \
    "${HANDOFF_UNIT}" "${HANDOFF_STATE_FILE}" "$(loginctl show-user "$(id -un)" -p Linger --value)"
  echo 'Remote Desktop Commander self-update staged; supervised restart handoff scheduled.'
  exit 0
fi

"${VERIFIER}" --restart
printf 'desktop_commander_version=%s\ndesktop_commander_source_sha=%s\nlinger=%s\n' \
  "${DESKTOP_COMMANDER_VERSION}" "${DESKTOP_COMMANDER_SOURCE_SHA}" "$(loginctl show-user "$(id -un)" -p Linger --value)"
echo 'Remote Desktop Commander user service installation completed.'
