#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
AUDIT_DIR="$REPO/runtime/deployments/$STAMP"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/nexolab-current-head-launch.lock"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
EDGE_ENV="$CENTRAL_DIR/.env.edge-central"
ROOT_ENV="$REPO/.env.local"
SUMMARY="$AUDIT_DIR/summary.txt"

mkdir -p "$AUDIT_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "ERROR: another NEXOLAB deployment is already running." >&2
  exit 75
fi

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$SUMMARY"
}

fail() {
  log "ERROR: $*"
  exit 1
}

on_error() {
  local rc=$?
  log "Deployment failed with exit code $rc. Evidence: $AUDIT_DIR"
  {
    echo
    echo '=== docker compose projects ==='
    docker compose ls 2>&1 || true
    echo
    echo '=== containers ==='
    docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>&1 || true
    echo
    echo '=== central logs ==='
    if [[ -f "$CENTRAL_ENV" ]]; then
      docker compose --env-file "$CENTRAL_ENV" \
        -f "$CENTRAL_DIR/compose.central.yaml" \
        -f "$CENTRAL_DIR/compose.observability.yaml" \
        logs --tail=250 --no-color 2>&1 || true
    fi
    echo
    echo '=== edge logs ==='
    if [[ -f "$EDGE_ENV" ]]; then
      docker compose --env-file "$EDGE_ENV" \
        -f "$CENTRAL_DIR/compose.edge.yaml" \
        -f "$CENTRAL_DIR/compose.hardware.yaml" \
        -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml" \
        logs --tail=250 --no-color 2>&1 || true
    fi
  } > "$AUDIT_DIR/failure-diagnostics.txt"
  exit "$rc"
}
trap on_error ERR

require() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

for command in git docker curl python3 openssl npm node flock; do
  require "$command"
done

docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
cd "$REPO"

log "Starting controlled current-head deployment"
log "Repository: $REPO"
log "Evidence: $AUDIT_DIR"

{
  echo '=== host ==='
  date --iso-8601=seconds
  hostnamectl 2>/dev/null || true
  uname -a
  free -h || true
  df -h / "$REPO" || true
  echo
  echo '=== git ==='
  git branch --show-current
  git rev-parse HEAD
  git log -5 --oneline
  git status --short
  echo
  echo '=== docker ==='
  docker version
  docker compose version
  docker compose ls
  docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
  docker volume ls
  echo
  echo '=== ports ==='
  sudo ss -ltnp || true
} > "$AUDIT_DIR/pre-deployment-inventory.txt" 2>&1

mkdir -p "$AUDIT_DIR/config-backup"
for file in \
  "$CENTRAL_DIR/.env.central" \
  "$CENTRAL_DIR/.env.edge" \
  "$CENTRAL_DIR/.env.edge-central" \
  "$CENTRAL_DIR/.env.edge-secure" \
  "$CENTRAL_DIR/.env.observability.local" \
  "$ROOT_ENV" \
  "$CENTRAL_DIR/m4-session-acceptance-local.py"; do
  if [[ -f "$file" ]]; then
    cp -a "$file" "$AUDIT_DIR/config-backup/"
  fi
done

git diff > "$AUDIT_DIR/tracked-working-tree.patch"
git diff --cached > "$AUDIT_DIR/tracked-index.patch"
git ls-files --others --exclude-standard > "$AUDIT_DIR/untracked-files.txt"

if [[ -d "$REPO/runtime/evidence" ]]; then
  tar -C "$REPO" -czf "$AUDIT_DIR/runtime-evidence.tar.gz" runtime/evidence
fi

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-before.json" 2>"$AUDIT_DIR/volume-identities-before.err" || true

PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=nexolab-central \
  --filter label=com.docker.compose.service=postgres \
  | head -n 1)"
if [[ -n "$PG_CONTAINER" ]]; then
  log "Creating PostgreSQL pre-upgrade backup"
  docker exec "$PG_CONTAINER" sh -ec \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$AUDIT_DIR/postgresql-pre-upgrade.dump"
  [[ -s "$AUDIT_DIR/postgresql-pre-upgrade.dump" ]] \
    || fail "PostgreSQL backup is empty"
else
  log "No running central PostgreSQL container found; skipping live pg_dump"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "tracked local changes detected; patches were saved in $AUDIT_DIR"
fi

log "Fetching current main"
git fetch --prune origin main
git switch main
git pull --ff-only origin main
CURRENT_HEAD="$(git rev-parse HEAD)"
ORIGIN_HEAD="$(git rev-parse origin/main)"
[[ "$CURRENT_HEAD" == "$ORIGIN_HEAD" ]] \
  || fail "local main is not at origin/main"
log "Current main: $CURRENT_HEAD"

env_get() {
  local file=$1 key=$2
  awk -F= -v key="$key" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "$file" 2>/dev/null || true
}

env_set() {
  local file=$1 key=$2 value=$3
  python3 - "$file" "$key" "$value" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
replacement = f"{key}={value}"
for index, line in enumerate(lines):
    if line.startswith(f"{key}="):
        lines[index] = replacement
        break
else:
    lines.append(replacement)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
}

ensure_secret() {
  local file=$1 key=$2
  local value
  value="$(env_get "$file" "$key")"
  if [[ -z "$value" || "$value" == replace-with-* ]]; then
    value="$(openssl rand -hex 32)"
    env_set "$file" "$key" "$value"
  fi
}

BIND_IP="$(env_get "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS)"
if [[ -z "$BIND_IP" || "$BIND_IP" == "127.0.0.1" ]]; then
  if ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx '172.20.10.10'; then
    BIND_IP='172.20.10.10'
  else
    BIND_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n 1)"
  fi
fi
[[ -n "$BIND_IP" ]] || fail "no trusted IPv4 address detected"
ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx "$BIND_IP" \
  || fail "CENTRAL_BIND_ADDRESS is not assigned to this host: $BIND_IP"
log "Trusted bind address: $BIND_IP"

if [[ ! -f "$CENTRAL_ENV" ]]; then
  if docker volume inspect nexolab-central-postgres-data >/dev/null 2>&1; then
    fail "existing PostgreSQL volume found but .env.central is missing"
  fi
  cp "$CENTRAL_DIR/.env.central.example" "$CENTRAL_ENV"
fi
chmod 0600 "$CENTRAL_ENV"

env_set "$CENTRAL_ENV" CENTRAL_RESOURCE_PREFIX nexolab-central
env_set "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS "$BIND_IP"
env_set "$CENTRAL_ENV" CENTRAL_API_PORT 8082
env_set "$CENTRAL_ENV" CENTRAL_MQTT_PORT 1884
env_set "$CENTRAL_ENV" CENTRAL_OBJECT_STORAGE_PORT 9000
env_set "$CENTRAL_ENV" CENTRAL_OBJECT_STORAGE_CONSOLE_PORT 9001
env_set "$CENTRAL_ENV" TELEMETRY_SERVICE_IMAGE nexolab-telemetry-service:local
env_set "$CENTRAL_ENV" MINIO_ROOT_USER nexolab-storage
ensure_secret "$CENTRAL_ENV" POSTGRES_PASSWORD
ensure_secret "$CENTRAL_ENV" MINIO_ROOT_PASSWORD
env_set "$CENTRAL_ENV" OBJECT_STORAGE_BUCKET nexolab-equipment-images
env_set "$CENTRAL_ENV" OBJECT_STORAGE_PUBLIC_ENDPOINT_URL "http://$BIND_IP:9000"
env_set "$CENTRAL_ENV" CORS_ALLOWED_ORIGINS \
  "http://127.0.0.1:3000,http://localhost:3000,http://$BIND_IP:3000"
env_set "$CENTRAL_ENV" CORS_ALLOW_CREDENTIALS false
env_set "$CENTRAL_ENV" AUTH_MODE disabled
env_set "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID \
  00000000-0000-0000-0000-000000000001
env_set "$CENTRAL_ENV" MQTT_NODE_REGISTRY_ENFORCED false
env_set "$CENTRAL_ENV" MQTT_TOPIC nexolab/telemetry
env_set "$CENTRAL_ENV" MQTT_CLIENT_ID nexolab-central-telemetry-ingestion
env_set "$CENTRAL_ENV" OBSERVABILITY_RESOURCE_PREFIX nexolab-observability
env_set "$CENTRAL_ENV" OBSERVABILITY_BIND_ADDRESS 127.0.0.1
env_set "$CENTRAL_ENV" PROMETHEUS_PORT 9090
env_set "$CENTRAL_ENV" ALERTMANAGER_PORT 9093
env_set "$CENTRAL_ENV" GRAFANA_PORT 3001
env_set "$CENTRAL_ENV" GRAFANA_ADMIN_USER nexolab-admin
ensure_secret "$CENTRAL_ENV" GRAFANA_ADMIN_PASSWORD

if [[ ! -f "$EDGE_ENV" ]]; then
  if [[ -f "$CENTRAL_DIR/.env.edge" ]]; then
    cp "$CENTRAL_DIR/.env.edge" "$EDGE_ENV"
  else
    fail ".env.edge-central is missing; real RS-485 settings cannot be invented"
  fi
fi
chmod 0600 "$EDGE_ENV"
RS485_DEVICE="$(env_get "$EDGE_ENV" RS485_HOST_DEVICE)"
[[ "$RS485_DEVICE" == /dev/serial/by-id/* ]] \
  || fail "RS485_HOST_DEVICE must use /dev/serial/by-id/..."
[[ -e "$RS485_DEVICE" ]] || fail "RS-485 adapter is not present: $RS485_DEVICE"
env_set "$EDGE_ENV" NEXOLAB_NODE_ID edge-01
env_set "$EDGE_ENV" DEVICE_AGENT_IMAGE nexolab-device-agent:local
env_set "$EDGE_ENV" CENTRAL_MQTT_HOST "$BIND_IP"
env_set "$EDGE_ENV" CENTRAL_MQTT_PORT 1884
env_set "$EDGE_ENV" CENTRAL_MQTT_TOPIC nexolab/telemetry
env_set "$EDGE_ENV" CENTRAL_API_BASE_URL "http://$BIND_IP:8082"
env_set "$EDGE_ENV" CENTRAL_WEBSOCKET_URL \
  "ws://$BIND_IP:8082/api/v1/telemetry/live"

cat > "$ROOT_ENV" <<EOF
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://$BIND_IP:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://$BIND_IP:8082/api/v1/telemetry/live
EOF
chmod 0600 "$ROOT_ENV"

mkdir -p "$REPO/runtime/observability"
chmod 0700 "$REPO/runtime/observability"
if [[ ! -f "$REPO/runtime/observability/disaster-recovery.prom" ]]; then
  cat > "$REPO/runtime/observability/disaster-recovery.prom" <<'EOF'
# Actual-host DR scheduler is not commissioned yet. Zero values are intentional and alertable.
# HELP nexolab_dr_last_verified_backup_timestamp_seconds Unix timestamp of the newest verified encrypted backup.
# TYPE nexolab_dr_last_verified_backup_timestamp_seconds gauge
nexolab_dr_last_verified_backup_timestamp_seconds 0
# HELP nexolab_dr_last_off_host_copy_timestamp_seconds Unix timestamp of the newest verified off-host copy.
# TYPE nexolab_dr_last_off_host_copy_timestamp_seconds gauge
nexolab_dr_last_off_host_copy_timestamp_seconds 0
# HELP nexolab_dr_last_restore_rehearsal_timestamp_seconds Unix timestamp of the newest restore rehearsal.
# TYPE nexolab_dr_last_restore_rehearsal_timestamp_seconds gauge
nexolab_dr_last_restore_rehearsal_timestamp_seconds 0
# HELP nexolab_dr_last_bundle_verification_success Whether the newest bundle passed verification.
# TYPE nexolab_dr_last_bundle_verification_success gauge
nexolab_dr_last_bundle_verification_success 0
EOF
  chmod 0600 "$REPO/runtime/observability/disaster-recovery.prom"
fi

log "Validating Compose models"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_DIR/compose.central.yaml" \
  -f "$CENTRAL_DIR/compose.observability.yaml" \
  config --quiet

docker compose --env-file "$EDGE_ENV" \
  -f "$CENTRAL_DIR/compose.edge.yaml" \
  -f "$CENTRAL_DIR/compose.hardware.yaml" \
  -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml" \
  config --quiet

log "Building current Device Agent image"
docker build --pull -t nexolab-device-agent:local "$REPO/services/device-agent"

log "Installing and building current frontend"
NODE_MAJOR="$(node -p 'Number(process.versions.node.split(".")[0])')"
(( NODE_MAJOR >= 22 )) || fail "Node.js 22+ is required; found $(node --version)"
if [[ -f package-lock.json ]]; then
  npm ci
else
  npm install
fi
npm run build

log "Starting central backend, MinIO and observability"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_DIR/compose.central.yaml" \
  -f "$CENTRAL_DIR/compose.observability.yaml" \
  up -d --build --wait

log "Starting real-hardware edge stack"
docker compose --env-file "$EDGE_ENV" \
  -f "$CENTRAL_DIR/compose.edge.yaml" \
  -f "$CENTRAL_DIR/compose.hardware.yaml" \
  -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml" \
  up -d --force-recreate mqtt device-agent

NPM_BIN="$(command -v npm)"
NODE_BIN_DIR="$(dirname "$(command -v node)")"
DASHBOARD_USER="$(id -un)"
DASHBOARD_GROUP="$(id -gn)"

sudo systemctl stop nexolab-dashboard.service >/dev/null 2>&1 || true
if [[ -f "$REPO/runtime/dashboard.pid" ]]; then
  OLD_PID="$(cat "$REPO/runtime/dashboard.pid" 2>/dev/null || true)"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
    kill "$OLD_PID" >/dev/null 2>&1 || true
  fi
fi
pkill -u "$DASHBOARD_USER" -f "$REPO/node_modules/.bin/next" >/dev/null 2>&1 || true
sleep 2

sudo tee /etc/systemd/system/nexolab-dashboard.service >/dev/null <<EOF
[Unit]
Description=NEXOLAB production dashboard
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=$DASHBOARD_USER
Group=$DASHBOARD_GROUP
WorkingDirectory=$REPO
Environment=NODE_ENV=production
Environment=PATH=$NODE_BIN_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$NPM_BIN run start -- --hostname 0.0.0.0 --port 3000
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now nexolab-dashboard.service

wait_http() {
  local label=$1 url=$2 attempts=${3:-60}
  local index
  for index in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 5 "$url" >/dev/null; then
      log "Ready: $label ($url)"
      return 0
    fi
    sleep 2
  done
  fail "timed out waiting for $label: $url"
}

wait_http telemetry "http://$BIND_IP:8082/health/ready" 90
wait_http device-agent "http://127.0.0.1:8081/health" 90
wait_http dashboard "http://127.0.0.1:3000" 90
wait_http prometheus "http://127.0.0.1:9090/-/ready" 90
wait_http alertmanager "http://127.0.0.1:9093/-/ready" 90
wait_http grafana "http://127.0.0.1:3001/api/health" 120
wait_http minio "http://$BIND_IP:9000/minio/health/live" 90

log "Running central smoke gate"
(
  cd "$CENTRAL_DIR"
  bash central-smoke.sh .env.central
) > "$AUDIT_DIR/central-smoke.txt" 2>&1

log "Verifying current API contracts"
python3 - "$BIND_IP" > "$AUDIT_DIR/api-contracts.txt" <<'PY'
import json
import sys
import urllib.request

host = sys.argv[1]
with urllib.request.urlopen(f"http://{host}:8082/openapi.json", timeout=15) as response:
    document = json.load(response)
paths = document.get("paths", {})
required = {
    "/api/v1/sessions",
    "/api/v1/nodes",
    "/api/v1/equipment/{equipment_id}/layout/draft",
    "/api/v1/reports",
    "/api/v1/alerts",
}
missing = sorted(path for path in required if path not in paths)
print("required routes:")
for path in sorted(required):
    print(f"  {'OK' if path in paths else 'MISSING'} {path}")
if missing:
    raise SystemExit(f"missing API routes: {missing}")
PY

{
  echo "deployed_at=$(date --iso-8601=seconds)"
  echo "commit=$CURRENT_HEAD"
  echo "bind_address=$BIND_IP"
  echo "dashboard=http://$BIND_IP:3000"
  echo "api=http://$BIND_IP:8082"
  echo "minio=http://$BIND_IP:9000"
  echo "grafana_local=http://127.0.0.1:3001"
  echo "prometheus_local=http://127.0.0.1:9090"
  echo "alertmanager_local=http://127.0.0.1:9093"
  echo
  echo '=== central ==='
  docker compose --env-file "$CENTRAL_ENV" \
    -f "$CENTRAL_DIR/compose.central.yaml" \
    -f "$CENTRAL_DIR/compose.observability.yaml" ps -a
  echo
  echo '=== edge ==='
  docker compose --env-file "$EDGE_ENV" \
    -f "$CENTRAL_DIR/compose.edge.yaml" \
    -f "$CENTRAL_DIR/compose.hardware.yaml" \
    -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml" ps -a
  echo
  echo '=== dashboard ==='
  sudo systemctl --no-pager --full status nexolab-dashboard.service || true
  echo
  echo '=== health ==='
  curl -fsS "http://$BIND_IP:8082/health/ready"
  echo
  curl -fsS "http://127.0.0.1:8081/health"
  echo
} > "$AUDIT_DIR/final-state.txt" 2>&1

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-after.json" 2>"$AUDIT_DIR/volume-identities-after.err" || true

log "DEPLOYMENT PASSED"
log "Dashboard: http://$BIND_IP:3000"
log "API: http://$BIND_IP:8082"
log "Grafana on Raspberry Pi: http://127.0.0.1:3001"
log "Evidence: $AUDIT_DIR"
log "Security note: compatibility MQTT is still on the trusted LAN; TLS cutover requires CA, exact broker DNS SAN and per-node credentials."
