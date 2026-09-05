#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="nexolab-inspection"
SERVICE_GROUP="nexolab-inspection"
PRIVATE_ROOT="/var/lib/nexolab-opera-inspection"
HELPER_ROOT="/usr/local/lib/nexolab-opera-inspection"
LEGACY_ROOT="/home/nexolab/runtime/inspection/opera-tailscale"
CONFIG_PATH="${PRIVATE_ROOT}/config.json"
CREDENTIAL_PATH="${PRIVATE_ROOT}/credential.json"
SERVICE_UNIT="/etc/systemd/system/nexolab-opera-inspection-login.service"
SOCKET_UNIT="/etc/systemd/system/nexolab-opera-inspection-login.socket"

systemctl stop nexolab-opera-inspection-login.service >/dev/null 2>&1 || true
systemctl stop nexolab-opera-inspection-login.socket >/dev/null 2>&1 || true

if ! getent passwd "${SERVICE_USER}" >/dev/null; then
  useradd --system --user-group --home-dir /nonexistent \
    --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

install -d -o root -g root -m 0755 "${HELPER_ROOT}"
install -o root -g root -m 0755 \
  "${SCRIPT_DIR}/opera_tailscale_login.py" \
  "${HELPER_ROOT}/opera_tailscale_login.py"

install -d -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" -m 0700 "${PRIVATE_ROOT}"

if [[ ! -f "${CONFIG_PATH}" && -f "${LEGACY_ROOT}/config.json" ]]; then
  mv "${LEGACY_ROOT}/config.json" "${CONFIG_PATH}"
fi
if [[ ! -f "${CREDENTIAL_PATH}" && -f "${LEGACY_ROOT}/secret/credential.json" ]]; then
  mv "${LEGACY_ROOT}/secret/credential.json" "${CREDENTIAL_PATH}"
fi

if [[ ! -f "${CONFIG_PATH}" ]]; then
  echo "Missing ${CONFIG_PATH}; create it from opera-tailscale-config.example.json." >&2
  exit 1
fi
if [[ ! -f "${CREDENTIAL_PATH}" ]]; then
  echo "Missing ${CREDENTIAL_PATH}; create the dedicated viewer credential first." >&2
  exit 1
fi

python3 - "${CONFIG_PATH}" <<'PY'
import ipaddress
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

path = Path(sys.argv[1])
document = json.loads(path.read_text(encoding="utf-8"))
expected_host = str(document.get("expected_host", "")).strip()
login_url = str(document.get("login_url", "")).strip()

if not expected_host or not login_url:
    raise SystemExit("config.json must contain expected_host and login_url")
parsed = urlsplit(login_url)
non_loopback_http = False
if parsed.scheme == "http" and parsed.hostname not in {None, "localhost"}:
    try:
        non_loopback_http = not ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        non_loopback_http = True
if non_loopback_http:
    document["login_url"] = f"https://{expected_host}/api/v1/auth/local/login"
document["credential_file"] = "/var/lib/nexolab-opera-inspection/credential.json"
temporary = path.with_suffix(".json.tmp")
temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY

chown "${SERVICE_USER}:${SERVICE_GROUP}" "${CONFIG_PATH}" "${CREDENTIAL_PATH}"
chmod 0600 "${CONFIG_PATH}" "${CREDENTIAL_PATH}"

install -m 0644 \
  "${SCRIPT_DIR}/systemd/nexolab-opera-inspection-login.socket" \
  "${SOCKET_UNIT}"
install -m 0644 \
  "${SCRIPT_DIR}/systemd/nexolab-opera-inspection-login.service" \
  "${SERVICE_UNIT}"

systemctl daemon-reload
systemctl enable --now nexolab-opera-inspection-login.socket

if id nexolab >/dev/null 2>&1 && runuser -u nexolab -- test -r "${CREDENTIAL_PATH}"; then
  echo "The ordinary nexolab account can still read the inspection credential." >&2
  exit 1
fi

printf 'inspection_service_user=%s\n' "${SERVICE_USER}"
printf 'inspection_private_dir_mode='; stat -c '%a' "${PRIVATE_ROOT}"
printf 'inspection_config_mode='; stat -c '%a' "${CONFIG_PATH}"
printf 'inspection_credential_mode='; stat -c '%a' "${CREDENTIAL_PATH}"
printf 'inspection_socket_enabled=%s\n' "$(systemctl is-enabled nexolab-opera-inspection-login.socket)"
printf 'inspection_socket_active=%s\n' "$(systemctl is-active nexolab-opera-inspection-login.socket)"
printf 'inspection_socket_metadata='; stat -c '%a %U %G' /run/nexolab-opera-inspection/login.sock

echo "Inspection helper installation/migration completed without printing credentials."
