#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${ROOT_DIR}/infrastructure/systemd/journald/60-nexolab-persistent.conf"
TARGET_DIR="${NEXOLAB_JOURNALD_CONF_DIR:-/etc/systemd/journald.conf.d}"
TARGET="${TARGET_DIR}/60-nexolab-persistent.conf"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: install-raspberry-pi-persistent-journal.sh [--dry-run]

Installs bounded persistent journald storage for NEXOLAB host reliability evidence.
Real installation requires root. Dry-run is unprivileged and performs no mutation.
EOF
}

while (($# > 0)); do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
if [[ ! -f "${SOURCE}" ]]; then
  printf 'Missing journald template: %s\n' "${SOURCE}" >&2
  exit 1
fi

if [[ "${DRY_RUN}" == "1" ]]; then
  printf 'dry_run=true\n'
  printf 'source=%s\n' "${SOURCE}"
  printf 'target=%s\n' "${TARGET}"
  grep -E '^(Storage|SystemMaxUse|SystemKeepFree|MaxRetentionSec|SyncIntervalSec)=' "${SOURCE}"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run the real installation as root." >&2
  exit 1
fi

if [[ ! -r /proc/device-tree/model ]] || ! grep -q 'Raspberry Pi' /proc/device-tree/model; then
  echo "Refusing to install Raspberry Pi journal policy without verified Raspberry Pi identity." >&2
  exit 1
fi

install -d -o root -g root -m 0755 "${TARGET_DIR}"
install -o root -g root -m 0644 "${SOURCE}" "${TARGET}"
systemctl restart systemd-journald.service
journalctl --flush
MARKER="nexolab-persistent-journal-$(date -u +%Y%m%dT%H%M%SZ)"
logger -t nexolab-remote-admin "${MARKER}"
sleep 1
journalctl --flush

EFFECTIVE="$(systemd-analyze cat-config systemd/journald.conf)"
effective_value() {
  local key="$1"
  awk -v key="${key}" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      value=$0
      sub(/^[^=]*=[[:space:]]*/, "", value)
      sub(/[[:space:]]+$/, "", value)
    }
    END { if (value == "") exit 1; print value }
  '
}
while IFS='=' read -r key expected; do
  actual="$(effective_value "${key}" <<<"${EFFECTIVE}" || true)"
  if [[ "${actual}" != "${expected}" ]]; then
    printf 'Effective journald %s mismatch: expected %s, got %s\n' "${key}" "${expected}" "${actual:-<unset>}" >&2
    exit 1
  fi
done < <(grep -E '^(Storage|SystemMaxUse|SystemKeepFree|MaxRetentionSec|SyncIntervalSec)=' "${SOURCE}")
if ! journalctl --directory=/var/log/journal -b --no-pager | grep -q "${MARKER}"; then
  echo "Persistent journal marker was not found in /var/log/journal." >&2
  exit 1
fi

printf 'journal_storage=persistent\n'
printf 'journal_target=%s\n' "${TARGET}"
printf 'journal_marker=%s\n' "${MARKER}"
journalctl --disk-usage
echo "Persistent host journal installation completed."
