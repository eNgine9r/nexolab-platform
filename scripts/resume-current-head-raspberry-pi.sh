#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/deployments/resume-current-head-$STAMP"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
EDGE_ENV="$CENTRAL_DIR/.env.edge-central"
CENTRAL_COMPOSE="$CENTRAL_DIR/compose.central.yaml"
OBS_COMPOSE="$CENTRAL_DIR/compose.observability.yaml"
EDGE_COMPOSE="$CENTRAL_DIR/compose.edge.yaml"
HARDWARE_COMPOSE="$CENTRAL_DIR/compose.hardware.yaml"
BRIDGE_COMPOSE="$CENTRAL_DIR/compose.edge-central-bridge.yaml"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/resume.log") 2>&1

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

on_error() {
  local rc=$?
  log "RESUME FAILED with exit code $rc"
  {
    echo '=== central ps ==='
    docker compose --env-file "$CENTRAL_ENV" \
      -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" ps -a || true
    echo
    echo '=== central logs ==='
    docker compose --env-file "$CENTRAL_ENV" \
      -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
      logs --tail=250 --no-color || true
    echo
    echo '=== edge ps ==='
    docker compose --env-file "$EDGE_ENV" \
      -f "$EDGE_COMPOSE" -f "$HARDWARE_COMPOSE" -f "$BRIDGE_COMPOSE" \
      ps -a || true
    echo
    echo '=== edge logs ==='
    docker compose --env-file "$EDGE_ENV" \
      -f "$EDGE_COMPOSE" -f "$HARDWARE_COMPOSE" -f "$BRIDGE_COMPOSE" \
      logs --tail=250 --no-color || true
    echo
    echo '=== dashboard ==='
    systemctl --no-pager --full status nexolab-dashboard.service || true
  } > "$EVIDENCE_DIR/failure-diagnostics.txt" 2>&1
  log "Evidence: $EVIDENCE_DIR"
  exit "$rc"
}
trap on_error ERR

cd "$REPO"

for required in "$CENTRAL_ENV" "$EDGE_ENV"; do
  [[ -f "$required" ]] || { echo "Missing required file: $required" >&2; exit 1; }
done

log "Normalizing tracked checkout permissions"
python3 - <<'PY'
from pathlib import Path
import os
import subprocess

root = Path.cwd()
entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"]).split(b"\0")
directories = set()
for entry in entries:
    if not entry:
        continue
    metadata, raw_path = entry.split(b"\t", 1)
    mode = metadata.split(b" ", 1)[0]
    path = root / os.fsdecode(raw_path)
    if not path.exists() or path.is_symlink():
        continue
    path.chmod(0o755 if mode == b"100755" else 0o644)
    parent = path.parent
    while parent != root:
        directories.add(parent)
        parent = parent.parent
for directory in sorted(directories, key=lambda item: len(item.parts)):
    directory.chmod(0o755)
PY

BIND_IP="$(awk -F= '$1 == "CENTRAL_BIND_ADDRESS" {print $2; exit}' "$CENTRAL_ENV")"
[[ -n "$BIND_IP" ]] || { echo 'CENTRAL_BIND_ADDRESS is empty' >&2; exit 1; }
log "Trusted bind address: $BIND_IP"

log "Ensuring central dependencies"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d --build postgres mqtt minio minio-init observability-alert-sink observability-textfile alertmanager

log "Running Alembic migration explicitly"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  run --rm telemetry-migrate

DB_REVISION="$(
  docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_COMPOSE" \
    exec -T postgres sh -ec \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version;"' \
  | tr -d '[:space:]'
)"
log "Database revision: $DB_REVISION"
[[ "$DB_REVISION" == "20260727_0016" ]] || {
  echo "Unexpected database revision: $DB_REVISION" >&2
  exit 1
}

log "Starting central application and observability"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d --wait telemetry-service prometheus grafana

log "Starting edge MQTT bridge and Device Agent"
docker compose --env-file "$EDGE_ENV" \
  -f "$EDGE_COMPOSE" -f "$HARDWARE_COMPOSE" -f "$BRIDGE_COMPOSE" \
  up -d --force-recreate mqtt device-agent

sleep 4
if ! curl -fsS --max-time 5 http://127.0.0.1:8081/health >/dev/null 2>&1; then
  if docker compose --env-file "$EDGE_ENV" \
    -f "$EDGE_COMPOSE" -f "$HARDWARE_COMPOSE" -f "$BRIDGE_COMPOSE" \
    logs --tail=120 --no-color device-agent \
    | grep -q 'attempt to write a readonly database'; then
    log "Repairing legacy Device Agent SQLite volume ownership"
    git show \
      origin/ops/raspberry-pi-current-head-launch:scripts/repair-edge-volume-ownership.sh \
      > "$EVIDENCE_DIR/repair-edge-volume-ownership.sh"
    chmod 0700 "$EVIDENCE_DIR/repair-edge-volume-ownership.sh"
    bash "$EVIDENCE_DIR/repair-edge-volume-ownership.sh"
  fi
fi

wait_http() {
  local label=$1 url=$2 attempts=${3:-90}
  local index
  for index in $(seq 1 "$attempts"); do
    if curl -fsS --max-time 5 "$url" >/dev/null; then
      log "Ready: $label ($url)"
      return 0
    fi
    sleep 2
  done
  echo "Timed out waiting for $label: $url" >&2
  return 1
}

wait_http telemetry "http://$BIND_IP:8082/health/ready" 90
wait_http device-agent "http://127.0.0.1:8081/health" 90

log "Ensuring dashboard systemd service"
sudo systemctl enable nexolab-dashboard.service >/dev/null
sudo systemctl restart nexolab-dashboard.service
wait_http dashboard "http://127.0.0.1:3000" 90
wait_http minio "http://$BIND_IP:9000/minio/health/live" 90
wait_http prometheus "http://127.0.0.1:9090/-/ready" 90
wait_http alertmanager "http://127.0.0.1:9093/-/ready" 90
wait_http grafana "http://127.0.0.1:3001/api/health" 120

log "Verifying security session endpoint"
curl -fsS "http://$BIND_IP:8082/api/v1/auth/session" \
  | tee "$EVIDENCE_DIR/security-session.json" \
  | python3 -m json.tool

log "Verifying Device Agent health"
curl -fsS http://127.0.0.1:8081/health \
  | tee "$EVIDENCE_DIR/device-agent-health.json" \
  | python3 -m json.tool

log "Verifying LAN CORS"
CORS_HEADER="$(
  curl -fsS -D - -o /dev/null \
    -H "Origin: http://$BIND_IP:3000" \
    "http://$BIND_IP:8082/api/v1/sessions?limit=1" \
  | tr -d '\r' \
  | grep -i '^access-control-allow-origin:' || true
)"
echo "$CORS_HEADER" | tee "$EVIDENCE_DIR/cors-header.txt"
[[ "$CORS_HEADER" == *"http://$BIND_IP:3000"* ]] || {
  echo 'LAN dashboard origin is not allowed by CORS' >&2
  exit 1
}

log "Verifying current API routes"
python3 - "$BIND_IP" <<'PY' | tee "$EVIDENCE_DIR/api-routes.txt"
import json
import sys
import urllib.request

host = sys.argv[1]
with urllib.request.urlopen(f"http://{host}:8082/openapi.json", timeout=15) as response:
    document = json.load(response)
paths = document.get("paths", {})
required = {
    "/api/v1/auth/session",
    "/api/v1/sessions",
    "/api/v1/nodes",
    "/api/v1/equipment/{equipment_id}/layout/draft",
    "/api/v1/reports",
    "/api/v1/alerts",
}
missing = sorted(required - set(paths))
for path in sorted(required):
    print(f"{'OK' if path in paths else 'MISSING'}: {path}")
if missing:
    raise SystemExit(f"Missing routes: {missing}")
PY

log "Running central smoke gate"
(
  cd "$CENTRAL_DIR"
  bash central-smoke.sh .env.central
) | tee "$EVIDENCE_DIR/central-smoke.txt"

log "Capturing final state"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" ps -a \
  | tee "$EVIDENCE_DIR/central-containers.txt"
docker compose --env-file "$EDGE_ENV" \
  -f "$EDGE_COMPOSE" -f "$HARDWARE_COMPOSE" -f "$BRIDGE_COMPOSE" ps -a \
  | tee "$EVIDENCE_DIR/edge-containers.txt"
sudo systemctl --no-pager --full status nexolab-dashboard.service \
  > "$EVIDENCE_DIR/dashboard-service.txt"

cat > "$EVIDENCE_DIR/manifest.txt" <<EOF
status=passed
completed_at=$(date --iso-8601=seconds)
commit=$(git rev-parse HEAD)
database_revision=$DB_REVISION
dashboard=http://$BIND_IP:3000
api=http://$BIND_IP:8082
evidence=$EVIDENCE_DIR
EOF

log "NEXOLAB CURRENT-HEAD RESUME PASSED"
echo "Dashboard: http://$BIND_IP:3000"
echo "API:       http://$BIND_IP:8082"
echo "Evidence:  $EVIDENCE_DIR"
