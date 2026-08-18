#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: deploy-version-manager-service.sh --source-root PATH

Installs the bounded NEXOLAB version-manager worker plus the optional GitHub update
maintenance plane. This prepares host contracts only; it does not stage, update,
roll back or activate NEXOLAB.
EOF
}

SOURCE_ROOT=""
while (($#)); do
  case "$1" in
    --source-root) SOURCE_ROOT="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$SOURCE_ROOT" ]] || { echo "--source-root is required" >&2; exit 2; }
SOURCE_ROOT="$(cd "$SOURCE_ROOT" && pwd)"
if [[ -d "$SOURCE_ROOT/infrastructure/offline" ]]; then
  UNIT_ROOT="$SOURCE_ROOT/infrastructure/offline"
elif [[ -d "$SOURCE_ROOT/deploy/offline" ]]; then
  UNIT_ROOT="$SOURCE_ROOT/deploy/offline"
else
  echo "Version-manager unit directory is missing under $SOURCE_ROOT" >&2
  exit 1
fi
UPDATE_UNIT_ROOT="$SOURCE_ROOT/infrastructure/systemd"
for file in \
  "$SOURCE_ROOT/scripts/nexolab-version-manager.py" \
  "$SOURCE_ROOT/scripts/nexolab-update-orchestrator.py" \
  "$SOURCE_ROOT/scripts/deploy-capacity-guard.sh" \
  "$UNIT_ROOT/nexolab-version-manager.service" \
  "$UNIT_ROOT/nexolab-version-manager.path" \
  "$UPDATE_UNIT_ROOT/nexolab-update-check.service" \
  "$UPDATE_UNIT_ROOT/nexolab-update-check.timer" \
  "$UPDATE_UNIT_ROOT/nexolab-update-request.service" \
  "$UPDATE_UNIT_ROOT/nexolab-update-request.path"; do
  [[ -f "$file" ]] || { echo "Required file is missing: $file" >&2; exit 1; }
done
[[ "$(id -u)" == "0" ]] || { echo "Run as root on the controlled NEXOLAB host" >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required" >&2; exit 1; }
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
command -v git >/dev/null || { echo "Git is required" >&2; exit 1; }
command -v runuser >/dev/null || { echo "runuser is required" >&2; exit 1; }

install -d -m 0750 /usr/local/lib/nexolab /var/backups/nexolab
install -d -o 10001 -g 10001 -m 0750 \
  /var/lib/nexolab/version-management \
  /var/lib/nexolab/version-management/operations \
  /var/lib/nexolab/version-management/requests \
  /var/lib/nexolab/version-management/update-check-requests \
  /var/lib/nexolab/version-management/update-check-rejected
install -d -o root -g root -m 0755 /var/lib/nexolab/version-management/catalog
install -m 0755 "$SOURCE_ROOT/scripts/nexolab-version-manager.py" /usr/local/lib/nexolab/nexolab-version-manager.py
install -m 0755 "$SOURCE_ROOT/scripts/nexolab-update-orchestrator.py" /usr/local/lib/nexolab/nexolab-update-orchestrator.py
install -m 0755 "$SOURCE_ROOT/scripts/deploy-capacity-guard.sh" /usr/local/lib/nexolab/deploy-capacity-guard.sh
install -m 0644 "$UNIT_ROOT/nexolab-version-manager.service" /etc/systemd/system/nexolab-version-manager.service
install -m 0644 "$UNIT_ROOT/nexolab-version-manager.path" /etc/systemd/system/nexolab-version-manager.path
install -m 0644 "$UPDATE_UNIT_ROOT/nexolab-update-check.service" /etc/systemd/system/nexolab-update-check.service
install -m 0644 "$UPDATE_UNIT_ROOT/nexolab-update-check.timer" /etc/systemd/system/nexolab-update-check.timer
install -m 0644 "$UPDATE_UNIT_ROOT/nexolab-update-request.service" /etc/systemd/system/nexolab-update-request.service
install -m 0644 "$UPDATE_UNIT_ROOT/nexolab-update-request.path" /etc/systemd/system/nexolab-update-request.path

if [[ ! -f /etc/nexolab/version-manager.env ]]; then
  install -d -m 0750 /etc/nexolab
  install -m 0640 /dev/null /etc/nexolab/version-manager.env
  cat > /etc/nexolab/version-manager.env <<'EOF'
NEXOLAB_VERSION_ROOT=/var/lib/nexolab/version-management
NEXOLAB_CENTRAL_ENV=/etc/nexolab/central.env
NEXOLAB_EDGE_ENV=/etc/nexolab/edge.env
NEXOLAB_VERSION_BACKUP_DIR=/var/backups/nexolab
NEXOLAB_VERSION_MANAGER_FLAGS=--local-auth
EOF
fi

if [[ ! -f /etc/nexolab/update-orchestrator.env ]]; then
  install -d -m 0750 /etc/nexolab
  install -m 0640 /dev/null /etc/nexolab/update-orchestrator.env
  cat > /etc/nexolab/update-orchestrator.env <<EOF
NEXOLAB_VERSION_ROOT=/var/lib/nexolab/version-management
NEXOLAB_REPOSITORY_PATH=$SOURCE_ROOT
NEXOLAB_GIT_USER=nexolab
NEXOLAB_VERSION_STATE_UID=10001
NEXOLAB_VERSION_STATE_GID=10001
EOF
fi

systemctl daemon-reload
systemctl enable --now nexolab-version-manager.path
systemctl enable --now nexolab-update-request.path
systemctl enable --now nexolab-update-check.timer

echo "NEXOLAB version-management workers installed."
echo "Automatic-update policy remains OFF until an administrator explicitly enables it."
echo "No version operation or GitHub update check was executed by this installer."
