#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/raspberry-pi-runtime-mode.sh
source "$SCRIPT_DIR/lib/raspberry-pi-runtime-mode.sh"
# shellcheck source=deploy-capacity-guard.sh
source "$SCRIPT_DIR/deploy-capacity-guard.sh"
# shellcheck source=lib/raspberry-pi-frontend-release.sh
source "$SCRIPT_DIR/lib/raspberry-pi-frontend-release.sh"

usage() {
  cat <<'USAGE'
Usage: deploy-current-head-raspberry-pi.sh [--runtime-mode lan|standalone] [--frontend-artifact PATH]

Options:
  --frontend-artifact PATH  Import a verified off-device frontend artifact instead of building on this host.

Modes:
  lan         Trusted-LAN dashboard and API exposure. This is the default.
  standalone  Loopback-only dashboard/API runtime for a locally attached browser.
USAGE
}

RUNTIME_MODE="lan"
FRONTEND_ARTIFACT_INPUT=""
while (($# > 0)); do
  case "$1" in
    --runtime-mode)
      (($# >= 2)) || {
        echo "ERROR: --runtime-mode requires lan or standalone" >&2
        exit 64
      }
      RUNTIME_MODE="$2"
      shift 2
      ;;
    --frontend-artifact)
      (($# >= 2)) || {
        echo "ERROR: --frontend-artifact requires an extracted artifact directory" >&2
        exit 64
      }
      FRONTEND_ARTIFACT_INPUT="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done
nexolab_validate_runtime_mode "$RUNTIME_MODE" || exit $?

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
FRONTEND_ARTIFACT_DIR=""
if [[ -n "$FRONTEND_ARTIFACT_INPUT" ]]; then
  [[ -d "$FRONTEND_ARTIFACT_INPUT" ]] || {
    echo "ERROR: frontend artifact directory not found: $FRONTEND_ARTIFACT_INPUT" >&2
    exit 66
  }
  FRONTEND_ARTIFACT_DIR="$(cd "$FRONTEND_ARTIFACT_INPUT" && pwd -P)"
fi
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
AUDIT_DIR="$REPO/runtime/deployments/$STAMP"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/nexolab-current-head-launch.lock"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
EDGE_ENV="$CENTRAL_DIR/.env.edge-central"
ROOT_ENV="$REPO/.env.local"
SUMMARY="$AUDIT_DIR/summary.txt"
RUNTIME_MODE_FILE="$REPO/runtime/runtime-mode"
FRONTEND_RELEASES_DIR="$REPO/runtime/frontend-releases"
FRONTEND_RELEASE_DIR=""

CENTRAL_COMPOSE_ARGS=(
  -f "$CENTRAL_DIR/compose.central.yaml"
  -f "$CENTRAL_DIR/compose.observability.yaml"
)
EDGE_COMPOSE_ARGS=(
  -f "$CENTRAL_DIR/compose.edge.yaml"
  -f "$CENTRAL_DIR/compose.hardware.yaml"
  -f "$CENTRAL_DIR/compose.edge-central-bridge.yaml"
)

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
  if [[ "${NEXOLAB_FRONTEND_ACTIVATED:-0}" != "1" && -n "${FRONTEND_RELEASE_DIR:-}" ]]; then
    nexolab_frontend_discard_unactivated_release "$FRONTEND_RELEASES_DIR" "$FRONTEND_RELEASE_DIR" || true
  fi
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
        "${CENTRAL_COMPOSE_ARGS[@]}" \
        logs --tail=250 --no-color 2>&1 || true
    fi
    echo
    echo '=== edge logs ==='
    if [[ -f "$EDGE_ENV" ]]; then
      docker compose --env-file "$EDGE_ENV" \
        "${EDGE_COMPOSE_ARGS[@]}" \
        logs --tail=250 --no-color 2>&1 || true
    fi
  } > "$AUDIT_DIR/failure-diagnostics.txt"
  exit "$rc"
}
trap on_error ERR

require() {
  command -v "$1" >/dev/null 2>&1 || fail "required command is missing: $1"
}

for command in git docker curl python3 openssl npm node flock ip sudo tar du df find sort stat mv rm ss sha256sum cp cmp install; do
  require "$command"
done

docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable"
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
cd "$REPO"

log "Starting controlled current-head deployment"
log "Repository: $REPO"
log "Runtime mode: $RUNTIME_MODE"
if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then log "Frontend candidate source: verified off-device artifact ($FRONTEND_ARTIFACT_DIR)"; else log "Frontend candidate source: bounded local build fallback"; fi
log "Evidence: $AUDIT_DIR"

PG_CONTAINER="$(docker ps -q \
  --filter label=com.docker.compose.project=nexolab-central \
  --filter label=com.docker.compose.service=postgres \
  | head -n 1)"

log "Applying bounded deployment-evidence retention"
if ! nexolab_prune_deployment_evidence "$REPO/runtime/deployments" "$AUDIT_DIR"; then
  fail "deployment evidence retention failed before runtime mutation"
fi
log "Running deployment capacity preflight before evidence capture"
if ! nexolab_capacity_preflight "$REPO" "$AUDIT_DIR" "$PG_CONTAINER" "$AUDIT_DIR/capacity-preflight.txt"; then
  fail "deployment capacity preflight failed before runtime mutation; see $AUDIT_DIR/capacity-preflight.txt"
fi

{
  echo '=== host ==='
  date --iso-8601=seconds
  hostnamectl 2>/dev/null || true
  uname -a
  free -h || true
  df -h / "$REPO" || true
  echo
  echo '=== network ==='
  ip -4 -br address || true
  ip route || true
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
  "$RUNTIME_MODE_FILE" \
  "$CENTRAL_DIR/m4-session-acceptance-local.py"; do
  if [[ -f "$file" ]]; then
    cp -a "$file" "$AUDIT_DIR/config-backup/"
  fi
done

git diff > "$AUDIT_DIR/tracked-working-tree.patch"
git diff --cached > "$AUDIT_DIR/tracked-index.patch"
git ls-files --others --exclude-standard > "$AUDIT_DIR/untracked-files.txt"

log "Rechecking deployment capacity immediately before large evidence writes"
if ! nexolab_capacity_preflight "$REPO" "$AUDIT_DIR" "$PG_CONTAINER" "$AUDIT_DIR/capacity-preflight.txt"; then
  fail "deployment capacity recheck failed before large writes; see $AUDIT_DIR/capacity-preflight.txt"
fi

if [[ -d "$REPO/runtime/evidence" ]]; then
  RUNTIME_ARCHIVE_TMP="$AUDIT_DIR/.runtime-evidence.tar.gz.partial"
  rm -f -- "$RUNTIME_ARCHIVE_TMP"
  if ! tar -C "$REPO" -czf "$RUNTIME_ARCHIVE_TMP" runtime/evidence; then
    rm -f -- "$RUNTIME_ARCHIVE_TMP"
    fail "runtime evidence archive failed; partial archive was removed"
  fi
  mv -- "$RUNTIME_ARCHIVE_TMP" "$AUDIT_DIR/runtime-evidence.tar.gz"
fi

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-central-telemetry-ingestion-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-before.json" 2>"$AUDIT_DIR/volume-identities-before.err" || true

if [[ -n "$PG_CONTAINER" ]]; then
  log "Creating PostgreSQL pre-upgrade backup"
  PG_DUMP_TMP="$AUDIT_DIR/.postgresql-pre-upgrade.dump.partial"
  rm -f -- "$PG_DUMP_TMP"
  if ! docker exec "$PG_CONTAINER" sh -ec \
    'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "$PG_DUMP_TMP"; then
    rm -f -- "$PG_DUMP_TMP"
    fail "PostgreSQL backup failed; partial dump was removed"
  fi
  if [[ ! -s "$PG_DUMP_TMP" ]]; then
    rm -f -- "$PG_DUMP_TMP"
    fail "PostgreSQL backup is empty; partial dump was removed"
  fi
  mv -- "$PG_DUMP_TMP" "$AUDIT_DIR/postgresql-pre-upgrade.dump"
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
[[ "$CURRENT_HEAD" == "$ORIGIN_HEAD" ]] || fail "local main is not at origin/main"
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

resolve_compose_path() {
  local value=$1
  if [[ "$value" == /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$CENTRAL_DIR" "$value"
  fi
}

if [[ ! -f "$CENTRAL_ENV" ]]; then
  if docker volume inspect nexolab-central-postgres-data >/dev/null 2>&1; then
    fail "existing PostgreSQL volume found but .env.central is missing"
  fi
  cp "$CENTRAL_DIR/.env.central.example" "$CENTRAL_ENV"
fi
chmod 0600 "$CENTRAL_ENV"

LAN_BIND_IP=""
if [[ "$RUNTIME_MODE" == "lan" ]]; then
  LAN_BIND_IP="$(env_get "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS)"
  if [[ -z "$LAN_BIND_IP" || "$LAN_BIND_IP" == "127.0.0.1" ]]; then
    if ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx '172.20.10.10'; then
      LAN_BIND_IP='172.20.10.10'
    else
      LAN_BIND_IP="$(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | head -n 1)"
    fi
  fi
  [[ -n "$LAN_BIND_IP" ]] || fail "no trusted IPv4 address detected for lan mode"
  ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1 | grep -qx "$LAN_BIND_IP" \
    || fail "CENTRAL_BIND_ADDRESS is not assigned to this host: $LAN_BIND_IP"
fi

nexolab_configure_runtime_contract "$RUNTIME_MODE" "$LAN_BIND_IP" || exit $?
BIND_IP="$NEXOLAB_HOST_BIND_ADDRESS"
log "Host bind address: $BIND_IP"
log "Dashboard origin: $NEXOLAB_DASHBOARD_ORIGIN"

if [[ "$NEXOLAB_USE_STANDALONE_OVERLAYS" == "true" ]]; then
  CENTRAL_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.central-standalone.yaml" )
  EDGE_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.edge-standalone.yaml" )
fi

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
env_set "$CENTRAL_ENV" OBJECT_STORAGE_PUBLIC_ENDPOINT_URL "$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL"
env_set "$CENTRAL_ENV" CORS_ALLOWED_ORIGINS "$NEXOLAB_CORS_ALLOWED_ORIGINS"
env_set "$CENTRAL_ENV" CORS_ALLOW_CREDENTIALS false
env_set "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID 00000000-0000-0000-0000-000000000001
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

AUTH_MODE_VALUE="$(env_get "$CENTRAL_ENV" AUTH_MODE)"
[[ -n "$AUTH_MODE_VALUE" ]] || fail "AUTH_MODE must be configured explicitly"
[[ "$AUTH_MODE_VALUE" != "disabled" ]] \
  || fail "AUTH_MODE=disabled is development-only and forbidden for controlled Raspberry Pi deployment"
log "Authentication mode preserved: $AUTH_MODE_VALUE"

LOCAL_AUTH_OVERLAY_ENABLED="false"
if [[ "$AUTH_MODE_VALUE" == "jwt" ]]; then
  LOCAL_PRIVATE="$(env_get "$CENTRAL_ENV" AUTH_LOCAL_PRIVATE_KEY_HOST_FILE)"
  LOCAL_PUBLIC="$(env_get "$CENTRAL_ENV" AUTH_LOCAL_PUBLIC_KEY_HOST_FILE)"
  JWKS_URL="$(env_get "$CENTRAL_ENV" AUTH_JWT_JWKS_URL)"
  if [[ -n "$LOCAL_PRIVATE" && -n "$LOCAL_PUBLIC" \
    && -r "$(resolve_compose_path "$LOCAL_PRIVATE")" \
    && -r "$(resolve_compose_path "$LOCAL_PUBLIC")" ]]; then
    CENTRAL_COMPOSE_ARGS+=( -f "$CENTRAL_DIR/compose.local-auth.yaml" )
    LOCAL_AUTH_OVERLAY_ENABLED="true"
    log "Enabled fail-closed local operator authentication overlay"
  elif [[ "$RUNTIME_MODE" == "standalone" && -n "$JWKS_URL" ]]; then
    fail "standalone mode cannot depend on remote AUTH_JWT_JWKS_URL; configure local auth keys or a local static key"
  else
    log "JWT profile preserved without local-auth overlay; operator-owned static provider settings remain authoritative"
  fi
fi

FRONTEND_AUTH_PROVIDER="disabled"
if [[ "$LOCAL_AUTH_OVERLAY_ENABLED" == "true" ]]; then
  FRONTEND_AUTH_PROVIDER="local"
fi
FRONTEND_ORGANIZATION_ID="$(env_get "$CENTRAL_ENV" AUTH_DEFAULT_ORGANIZATION_ID)"
[[ -n "$FRONTEND_ORGANIZATION_ID" ]] || fail "AUTH_DEFAULT_ORGANIZATION_ID must be configured"

if [[ ! -f "$EDGE_ENV" ]]; then
  if [[ -f "$CENTRAL_DIR/.env.edge" ]]; then
    cp "$CENTRAL_DIR/.env.edge" "$EDGE_ENV"
  else
    fail ".env.edge-central is missing; real RS-485 settings cannot be invented"
  fi
fi
chmod 0600 "$EDGE_ENV"
RS485_DEVICE="$(env_get "$EDGE_ENV" RS485_HOST_DEVICE)"
[[ "$RS485_DEVICE" == /dev/serial/by-id/* ]] || fail "RS485_HOST_DEVICE must use /dev/serial/by-id/..."
[[ -e "$RS485_DEVICE" ]] || fail "RS-485 adapter is not present: $RS485_DEVICE"
env_set "$EDGE_ENV" NEXOLAB_NODE_ID edge-01
env_set "$EDGE_ENV" DEVICE_AGENT_IMAGE nexolab-device-agent:local
env_set "$EDGE_ENV" CENTRAL_RUNTIME_NETWORK nexolab-central
env_set "$EDGE_ENV" CENTRAL_MQTT_HOST "$NEXOLAB_EDGE_CENTRAL_MQTT_HOST"
env_set "$EDGE_ENV" CENTRAL_MQTT_PORT "$NEXOLAB_EDGE_CENTRAL_MQTT_PORT"
env_set "$EDGE_ENV" CENTRAL_MQTT_TOPIC nexolab/telemetry
env_set "$EDGE_ENV" CENTRAL_API_BASE_URL "$NEXOLAB_EDGE_CENTRAL_API_BASE_URL"
env_set "$EDGE_ENV" CENTRAL_WEBSOCKET_URL "$NEXOLAB_EDGE_CENTRAL_WEBSOCKET_URL"

cat > "$ROOT_ENV" <<EOF_ENV
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=$NEXOLAB_API_BASE_URL
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=$NEXOLAB_WEBSOCKET_URL
NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$FRONTEND_AUTH_PROVIDER
NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$FRONTEND_ORGANIZATION_ID
EOF_ENV
chmod 0600 "$ROOT_ENV"

if [[ "$LOCAL_AUTH_OVERLAY_ENABLED" == "true" ]]; then
  [[ "$(env_get "$ROOT_ENV" NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER)" == "local" ]] \
    || fail "local-auth overlay requires NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local before dashboard build"
  [[ "$(env_get "$ROOT_ENV" NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID)" == "$FRONTEND_ORGANIZATION_ID" ]] \
    || fail "local-auth overlay requires dashboard organization scope to match AUTH_DEFAULT_ORGANIZATION_ID"
fi

mkdir -p "$REPO/runtime/observability"
chmod 0700 "$REPO/runtime/observability"
if [[ ! -f "$REPO/runtime/observability/disaster-recovery.prom" ]]; then
  cat > "$REPO/runtime/observability/disaster-recovery.prom" <<'EOF_PROM'
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
EOF_PROM
  chmod 0600 "$REPO/runtime/observability/disaster-recovery.prom"
fi

log "Validating Compose models"
docker compose --env-file "$CENTRAL_ENV" "${CENTRAL_COMPOSE_ARGS[@]}" config --quiet
docker compose --env-file "$EDGE_ENV" "${EDGE_COMPOSE_ARGS[@]}" config --quiet

if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then
  log "Skipping frontend build headroom gate because a verified off-device artifact was supplied"
  {
    echo 'status=SKIPPED_OFF_DEVICE_ARTIFACT'
    echo "mem_available_kib=$(nexolab_frontend_mem_available_kib)"
    echo "swap_free_kib=$(nexolab_frontend_swap_free_kib)"
  } > "$AUDIT_DIR/frontend-resource-preflight.txt"
else
  log "Checking frontend deployment resource headroom for bounded local build fallback"
  if ! nexolab_frontend_resource_preflight "$AUDIT_DIR/frontend-resource-preflight.txt"; then
    fail "frontend resource preflight failed before candidate build; active dashboard was not touched"
  fi
fi
if ! nexolab_frontend_assert_no_competing_builds "$AUDIT_DIR/frontend-competing-processes.txt"; then
  fail "another heavy build/acceptance workload is active; refusing concurrent production deployment"
fi

log "Building current Device Agent image"
docker build --pull -t nexolab-device-agent:local "$REPO/services/device-agent"

EXPECTED_NODE_VERSION="$(tr -d '[:space:]' < "$REPO/.nvmrc")"
[[ -n "$EXPECTED_NODE_VERSION" ]] || fail "repository .nvmrc is empty"
ACTUAL_NODE_VERSION="$(node --version | sed 's/^v//')"
[[ "$ACTUAL_NODE_VERSION" == "$EXPECTED_NODE_VERSION" ]] \
  || fail "host Node version $ACTUAL_NODE_VERSION does not match repository baseline $EXPECTED_NODE_VERSION"
FRONTEND_RELEASE_DIR="$FRONTEND_RELEASES_DIR/${CURRENT_HEAD}-${STAMP}"
mkdir -p "$FRONTEND_RELEASES_DIR"
log "Preparing immutable frontend candidate: $FRONTEND_RELEASE_DIR"
if ! nexolab_frontend_prepare_release_source "$REPO" "$CURRENT_HEAD" "$FRONTEND_RELEASE_DIR" "$ROOT_ENV"; then
  fail "failed to prepare immutable frontend candidate source"
fi

if [[ -n "$FRONTEND_ARTIFACT_DIR" ]]; then
  log "Importing verified off-device frontend artifact"
  if ! nexolab_frontend_import_artifact \
    "$FRONTEND_ARTIFACT_DIR" \
    "$REPO" \
    "$FRONTEND_RELEASE_DIR" \
    "$CURRENT_HEAD" \
    live \
    "$NEXOLAB_API_BASE_URL" \
    "$NEXOLAB_WEBSOCKET_URL" \
    "$FRONTEND_AUTH_PROVIDER" \
    "$FRONTEND_ORGANIZATION_ID" \
    "$AUDIT_DIR/frontend-artifact-import.txt"; then
    fail "off-device frontend artifact verification/import failed; active dashboard was not touched"
  fi
  printf '%s\n' 'status=SKIPPED_OFF_DEVICE_ARTIFACT' > "$AUDIT_DIR/frontend-build.txt"
else
  log "Building frontend candidate inside a bounded container"
  export NEXOLAB_FRONTEND_BUILD_IMAGE="${NEXOLAB_FRONTEND_BUILD_IMAGE:-node:${EXPECTED_NODE_VERSION}-bookworm-slim}"
  if ! nexolab_frontend_build_release \
    "$FRONTEND_RELEASE_DIR" \
    live \
    "$NEXOLAB_API_BASE_URL" \
    "$NEXOLAB_WEBSOCKET_URL" \
    "$FRONTEND_AUTH_PROVIDER" \
    "$FRONTEND_ORGANIZATION_ID" \
    > "$AUDIT_DIR/frontend-build.txt" 2>&1; then
    fail "bounded frontend candidate build failed; active dashboard was not touched"
  fi
fi

log "Verifying compiled frontend public runtime contract"
if ! nexolab_frontend_verify_public_contract \
  "$FRONTEND_RELEASE_DIR" \
  live \
  "$NEXOLAB_API_BASE_URL" \
  "$NEXOLAB_WEBSOCKET_URL" \
  "$FRONTEND_AUTH_PROVIDER" \
  "$FRONTEND_ORGANIZATION_ID" \
  "$AUDIT_DIR/frontend-public-contract.txt"; then
  fail "frontend candidate public runtime contract does not match this deployment"
fi
nexolab_frontend_write_provenance \
  "$FRONTEND_RELEASE_DIR" \
  "$CURRENT_HEAD" \
  "$RUNTIME_MODE" \
  "$NEXOLAB_API_BASE_URL" \
  "$NEXOLAB_WEBSOCKET_URL" \
  "$FRONTEND_AUTH_PROVIDER" \
  "$FRONTEND_ORGANIZATION_ID"

FRONTEND_CANDIDATE_PORT="${NEXOLAB_FRONTEND_CANDIDATE_PORT:-3100}"
if ss -ltn | awk '{print $4}' | grep -Eq "(^|:)$FRONTEND_CANDIDATE_PORT$"; then
  fail "frontend candidate verification port is already in use: $FRONTEND_CANDIDATE_PORT"
fi
log "Starting frontend candidate on isolated port $FRONTEND_CANDIDATE_PORT"
(
  cd "$FRONTEND_RELEASE_DIR"
  NEXT_PUBLIC_NEXOLAB_DATA_MODE=live \
  NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$NEXOLAB_API_BASE_URL" \
  NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="$NEXOLAB_WEBSOCKET_URL" \
  NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="$FRONTEND_AUTH_PROVIDER" \
  NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$FRONTEND_ORGANIZATION_ID" \
  NEXT_TELEMETRY_DISABLED=1 \
  "$FRONTEND_RELEASE_DIR/node_modules/.bin/next" start \
    --hostname 127.0.0.1 --port "$FRONTEND_CANDIDATE_PORT"
) > "$AUDIT_DIR/frontend-candidate.txt" 2>&1 &
FRONTEND_CANDIDATE_PID=$!
FRONTEND_CANDIDATE_READY=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "http://127.0.0.1:$FRONTEND_CANDIDATE_PORT/" >/dev/null; then
    FRONTEND_CANDIDATE_READY=true
    break
  fi
  if ! kill -0 "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
if [[ "$FRONTEND_CANDIDATE_READY" != true ]]; then
  kill "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true
  wait "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true
  fail "frontend candidate did not become ready; active dashboard was not touched"
fi
for route in / /nodes /live /energy /sessions; do
  curl -fsS --max-time 5 "http://127.0.0.1:$FRONTEND_CANDIDATE_PORT$route" >/dev/null \
    || { kill "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true; wait "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true; fail "frontend candidate route failed: $route"; }
done
kill "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true
wait "$FRONTEND_CANDIDATE_PID" >/dev/null 2>&1 || true
FRONTEND_CANDIDATE_PID=""
log "Frontend candidate verified without mutating the active dashboard"

log "Starting central backend, MinIO and observability"
docker compose --env-file "$CENTRAL_ENV" \
  "${CENTRAL_COMPOSE_ARGS[@]}" \
  up -d --build --wait

log "Starting real-hardware edge stack"
docker compose --env-file "$EDGE_ENV" \
  "${EDGE_COMPOSE_ARGS[@]}" \
  up -d --force-recreate mqtt device-agent

NODE_BIN_DIR="$(dirname "$(command -v node)")"
DASHBOARD_USER="$(id -un)"
DASHBOARD_GROUP="$(id -gn)"
DASHBOARD_UNIT="/etc/systemd/system/nexolab-dashboard.service"
DASHBOARD_UNIT_BACKUP="$AUDIT_DIR/dashboard-unit-before.service"
DASHBOARD_UNIT_CANDIDATE="$AUDIT_DIR/dashboard-unit-candidate.service"

if sudo test -f "$DASHBOARD_UNIT"; then
  sudo cp -a "$DASHBOARD_UNIT" "$DASHBOARD_UNIT_BACKUP"
  sudo chown "$DASHBOARD_USER:$DASHBOARD_GROUP" "$DASHBOARD_UNIT_BACKUP" || true
fi

cat > "$DASHBOARD_UNIT_CANDIDATE" <<EOF_UNIT
[Unit]
Description=NEXOLAB production dashboard
After=$NEXOLAB_SYSTEMD_AFTER
$(if [[ -n "$NEXOLAB_SYSTEMD_WANTS" ]]; then printf 'Wants=%s\n' "$NEXOLAB_SYSTEMD_WANTS"; fi)

[Service]
Type=simple
User=$DASHBOARD_USER
Group=$DASHBOARD_GROUP
WorkingDirectory=$FRONTEND_RELEASE_DIR
Environment=NODE_ENV=production
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
Environment=NEXT_PUBLIC_NEXOLAB_API_BASE_URL=$NEXOLAB_API_BASE_URL
Environment=NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=$NEXOLAB_WEBSOCKET_URL
Environment=NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$FRONTEND_AUTH_PROVIDER
Environment=NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$FRONTEND_ORGANIZATION_ID
Environment=PATH=$NODE_BIN_DIR:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$FRONTEND_RELEASE_DIR/node_modules/.bin/next start --hostname $NEXOLAB_DASHBOARD_BIND_ADDRESS --port 3000
Restart=always
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
EOF_UNIT

rollback_dashboard_release() {
  log "Rolling back dashboard service to the last-known-good unit"
  sudo systemctl stop nexolab-dashboard.service >/dev/null 2>&1 || true
  if [[ -f "$DASHBOARD_UNIT_BACKUP" ]]; then
    sudo install -m 0644 "$DASHBOARD_UNIT_BACKUP" "$DASHBOARD_UNIT"
    sudo systemctl daemon-reload
    sudo systemctl start nexolab-dashboard.service >/dev/null 2>&1 || true
  else
    sudo rm -f "$DASHBOARD_UNIT"
    sudo systemctl daemon-reload
  fi
}

log "Activating verified frontend release"
sudo systemctl stop nexolab-dashboard.service >/dev/null 2>&1 || true
if [[ -f "$REPO/runtime/dashboard.pid" ]]; then
  OLD_PID="$(cat "$REPO/runtime/dashboard.pid" 2>/dev/null || true)"
  if [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
    kill "$OLD_PID" >/dev/null 2>&1 || true
  fi
fi
sudo install -m 0644 "$DASHBOARD_UNIT_CANDIDATE" "$DASHBOARD_UNIT"
sudo systemctl daemon-reload
sudo systemctl enable nexolab-dashboard.service >/dev/null
if ! sudo systemctl start nexolab-dashboard.service; then
  rollback_dashboard_release
  fail "verified frontend release failed to start; last-known-good dashboard unit restored"
fi
DASHBOARD_ACTIVATED=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 "$NEXOLAB_DASHBOARD_ORIGIN" >/dev/null; then
    DASHBOARD_ACTIVATED=true
    break
  fi
  sleep 1
done
if [[ "$DASHBOARD_ACTIVATED" != true ]]; then
  rollback_dashboard_release
  fail "verified frontend release failed post-activation health check; last-known-good dashboard restored"
fi
NEXOLAB_FRONTEND_ACTIVATED=1
log "Activated frontend release: $FRONTEND_RELEASE_DIR"

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
  log "Not ready after activation: $label ($url)"
  return 1
}

wait_http_or_rollback() {
  local label=$1
  if wait_http "$@"; then
    return 0
  fi
  rollback_dashboard_release
  fail "post-activation readiness failed for $label; last-known-good dashboard restored"
}

wait_http_or_rollback telemetry "$NEXOLAB_API_BASE_URL/health/ready" 90
wait_http_or_rollback device-agent "http://127.0.0.1:8081/health" 90
wait_http_or_rollback dashboard "$NEXOLAB_DASHBOARD_ORIGIN" 90
wait_http_or_rollback prometheus "http://127.0.0.1:9090/-/ready" 90
wait_http_or_rollback alertmanager "http://127.0.0.1:9093/-/ready" 90
wait_http_or_rollback grafana "http://127.0.0.1:3001/api/health" 120
wait_http_or_rollback minio "$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL/minio/health/live" 90

log "Running central smoke gate"
(
  cd "$CENTRAL_DIR"
  bash central-smoke.sh .env.central
) > "$AUDIT_DIR/central-smoke.txt" 2>&1

log "Verifying current API contracts"
python3 - "$NEXOLAB_API_BASE_URL" "$LOCAL_AUTH_OVERLAY_ENABLED" > "$AUDIT_DIR/api-contracts.txt" <<'PY'
import json
import sys
import urllib.request

base_url = sys.argv[1]
local_auth_enabled = sys.argv[2].lower() == "true"
with urllib.request.urlopen(f"{base_url}/openapi.json", timeout=15) as response:
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
if local_auth_enabled:
    required.update(
        {
            "/api/v1/auth/local/login",
            "/api/v1/admin/users",
        }
    )
missing = sorted(path for path in required if path not in paths)
print("required routes:")
for path in sorted(required):
    print(f"  {'OK' if path in paths else 'MISSING'} {path}")
if missing:
    raise SystemExit(f"missing API routes: {missing}")
PY

mkdir -p "$REPO/runtime"
printf '%s\n' "$RUNTIME_MODE" > "$AUDIT_DIR/runtime-mode"
install -m 0600 "$AUDIT_DIR/runtime-mode" "$RUNTIME_MODE_FILE"

{
  echo "deployed_at=$(date --iso-8601=seconds)"
  echo "commit=$CURRENT_HEAD"
  echo "runtime_mode=$RUNTIME_MODE"
  echo "bind_address=$BIND_IP"
  echo "dashboard=$NEXOLAB_DASHBOARD_ORIGIN"
  echo "api=$NEXOLAB_API_BASE_URL"
  echo "minio=$NEXOLAB_OBJECT_STORAGE_PUBLIC_URL"
  echo "auth_mode=$AUTH_MODE_VALUE"
  echo "local_auth_overlay=$LOCAL_AUTH_OVERLAY_ENABLED"
  echo "dashboard_auth_provider=$FRONTEND_AUTH_PROVIDER"
  echo "dashboard_organization_id=$FRONTEND_ORGANIZATION_ID"
  echo "frontend_release_dir=$FRONTEND_RELEASE_DIR"
  echo "frontend_build_id=$(cat "$FRONTEND_RELEASE_DIR/.next/BUILD_ID")"
  echo "grafana_local=http://127.0.0.1:3001"
  echo "prometheus_local=http://127.0.0.1:9090"
  echo "alertmanager_local=http://127.0.0.1:9093"
  echo
  echo '=== central ==='
  docker compose --env-file "$CENTRAL_ENV" "${CENTRAL_COMPOSE_ARGS[@]}" ps -a
  echo
  echo '=== edge ==='
  docker compose --env-file "$EDGE_ENV" "${EDGE_COMPOSE_ARGS[@]}" ps -a
  echo
  echo '=== dashboard ==='
  sudo systemctl --no-pager --full status nexolab-dashboard.service || true
  echo
  echo '=== health ==='
  curl -fsS "$NEXOLAB_API_BASE_URL/health/ready"
  echo
  curl -fsS "http://127.0.0.1:8081/health"
  echo
} > "$AUDIT_DIR/final-state.txt" 2>&1

docker volume inspect \
  nexolab-central-postgres-data \
  nexolab-central-mqtt-data \
  nexolab-central-object-storage-data \
  nexolab-central-telemetry-ingestion-data \
  nexolab-edge_edge-data \
  nexolab-edge_mqtt-data \
  > "$AUDIT_DIR/volume-identities-after.json" 2>"$AUDIT_DIR/volume-identities-after.err" || true

log "DEPLOYMENT PASSED"
log "Runtime mode: $RUNTIME_MODE"
log "Dashboard: $NEXOLAB_DASHBOARD_ORIGIN"
log "API: $NEXOLAB_API_BASE_URL"
log "Grafana on Raspberry Pi: http://127.0.0.1:3001"
log "Evidence: $AUDIT_DIR"
log "Security note: standalone mode is loopback-only; lan mode retains trusted-LAN exposure. MQTT TLS cutover remains a separate controlled gate."
