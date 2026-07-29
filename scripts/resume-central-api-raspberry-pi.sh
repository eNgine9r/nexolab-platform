#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/deployments/resume-central-api-$STAMP"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
CENTRAL_COMPOSE="$CENTRAL_DIR/compose.central.yaml"
OBS_COMPOSE="$CENTRAL_DIR/compose.observability.yaml"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/resume-central-api.log") 2>&1

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

on_error() {
  local rc=$?
  log "CENTRAL API RESUME FAILED with exit code $rc"
  docker compose --env-file "$CENTRAL_ENV" \
    -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" ps -a \
    > "$EVIDENCE_DIR/central-ps.txt" 2>&1 || true
  docker compose --env-file "$CENTRAL_ENV" \
    -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
    logs --tail=250 --no-color postgres mqtt minio telemetry-service alertmanager prometheus grafana \
    > "$EVIDENCE_DIR/central-logs.txt" 2>&1 || true
  log "Evidence: $EVIDENCE_DIR"
  exit "$rc"
}
trap on_error ERR

cd "$REPO"
[[ -f "$CENTRAL_ENV" ]] || { echo "Missing $CENTRAL_ENV" >&2; exit 1; }

BIND_IP="$(awk -F= '$1 == "CENTRAL_BIND_ADDRESS" {print $2; exit}' "$CENTRAL_ENV")"
[[ -n "$BIND_IP" ]] || { echo 'CENTRAL_BIND_ADDRESS is empty' >&2; exit 1; }

log "Normalizing runtime-readable configuration permissions"
if [[ -d infrastructure/observability ]]; then
  find infrastructure/observability -type d -exec chmod 0755 {} +
  find infrastructure/observability -type f -exec chmod 0644 {} +
fi
find services/telemetry-service -type d -exec chmod 0755 {} +
find services/telemetry-service -type f -exec chmod 0644 {} +
chmod 0755 services/telemetry-service/bin/nexolab-dynsec-admin 2>/dev/null || true

log "Rebuilding telemetry image from normalized source"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  build telemetry-migrate telemetry-service

log "Starting core central dependencies"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d postgres mqtt minio minio-init observability-alert-sink observability-textfile alertmanager

log "Running Alembic migration"
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

log "Starting Telemetry Service"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d --force-recreate telemetry-service

for attempt in $(seq 1 90); do
  if curl -fsS --max-time 5 "http://$BIND_IP:8082/health/ready" \
    > "$EVIDENCE_DIR/telemetry-ready.json"; then
    log "Telemetry Service is ready"
    break
  fi
  if [[ "$attempt" == 90 ]]; then
    echo 'Telemetry Service readiness timeout' >&2
    exit 1
  fi
  sleep 2
done

log "Verifying security session"
curl -fsS --max-time 10 "http://$BIND_IP:8082/api/v1/auth/session" \
  | tee "$EVIDENCE_DIR/security-session.json" \
  | python3 -m json.tool

log "Starting remaining observability services"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d prometheus grafana

log "Verifying LAN CORS"
CORS_HEADER="$(
  curl -fsS -D - -o /dev/null \
    -H "Origin: http://$BIND_IP:3000" \
    "http://$BIND_IP:8082/api/v1/auth/session" \
  | tr -d '\r' \
  | grep -i '^access-control-allow-origin:' || true
)"
echo "$CORS_HEADER" | tee "$EVIDENCE_DIR/cors-header.txt"
[[ "$CORS_HEADER" == *"http://$BIND_IP:3000"* ]] || {
  echo 'LAN dashboard origin is not allowed by CORS' >&2
  exit 1
}

docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" ps -a \
  | tee "$EVIDENCE_DIR/central-ps.txt"

cat > "$EVIDENCE_DIR/manifest.txt" <<EOF
status=passed
completed_at=$(date --iso-8601=seconds)
commit=$(git rev-parse HEAD)
database_revision=$DB_REVISION
dashboard=http://$BIND_IP:3000
api=http://$BIND_IP:8082
evidence=$EVIDENCE_DIR
EOF

log "NEXOLAB CENTRAL API RESUME PASSED"
echo "Dashboard: http://$BIND_IP:3000"
echo "API:       http://$BIND_IP:8082"
echo "Evidence:  $EVIDENCE_DIR"
