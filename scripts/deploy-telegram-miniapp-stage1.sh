#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infrastructure/compose"
CENTRAL_ENV="${NEXOLAB_CENTRAL_ENV:-$COMPOSE_DIR/.env.central}"
SECRET_DIR="${NEXOLAB_TELEGRAM_SECRET_DIR:-/etc/nexolab/telegram}"
TELEGRAM_ENV="$SECRET_DIR/telegram.env"
EVIDENCE_ROOT="${NEXOLAB_TG04_EVIDENCE_ROOT:-$REPO_ROOT/runtime/evidence}"
LOCK_FILE="${NEXOLAB_TG04_LOCK_FILE:-/run/lock/nexolab-tg04-stage1.lock}"
EXPECTED_SOURCE=""
APPROVED="0"
SUCCESS="0"
STARTED="0"

usage() {
  cat <<'USAGE'
Usage: deploy-telegram-miniapp-stage1.sh \
  --expected-source-sha SHA \
  --approve-miniapp-only

Starts only the optional Telegram Mini App runtime. Telegram delivery remains disabled.
USAGE
}
while (($# > 0)); do
  case "$1" in
    --expected-source-sha)
      (($# >= 2)) || { echo "ERROR: --expected-source-sha requires SHA" >&2; exit 64; }
      EXPECTED_SOURCE="$2"
      shift 2
      ;;
    --approve-miniapp-only)
      APPROVED="1"
      shift
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

[[ "$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo "ERROR: exact lowercase SHA required" >&2; exit 64; }
[[ "$APPROVED" == "1" ]] || { echo "ERROR: explicit --approve-miniapp-only is required" >&2; exit 64; }
[[ "$EUID" -eq 0 ]] || { echo "ERROR: root_required" >&2; exit 77; }
for command in git docker curl python3 flock sha256sum tailscale; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing command: $command" >&2; exit 69; }
done

docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose unavailable" >&2; exit 69; }
[[ -f "$CENTRAL_ENV" && ! -L "$CENTRAL_ENV" ]] || { echo "ERROR: central env unavailable" >&2; exit 66; }
[[ -f "$TELEGRAM_ENV" && ! -L "$TELEGRAM_ENV" ]] || { echo "ERROR: protected Telegram env unavailable" >&2; exit 66; }
[[ -f "$COMPOSE_DIR/compose.central.yaml" && -f "$COMPOSE_DIR/compose.telegram.yaml" ]] \
  || { echo "ERROR: compose contract unavailable" >&2; exit 66; }

cd "$REPO_ROOT"
GIT=(git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT")
ACTUAL_SOURCE="$("${GIT[@]}" rev-parse HEAD)"
[[ "$ACTUAL_SOURCE" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: source SHA mismatch" >&2; exit 65; }
"${GIT[@]}" diff --quiet -- . || { echo "ERROR: tracked working tree is dirty" >&2; exit 65; }
"${GIT[@]}" diff --cached --quiet -- . || { echo "ERROR: staged working tree is dirty" >&2; exit 65; }

mkdir -p "$EVIDENCE_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/tg04-telegram-stage1-$STAMP"
mkdir -m 0700 "$EVIDENCE_DIR"
SUMMARY="$EVIDENCE_DIR/summary.txt"
BUILD_LOG="$EVIDENCE_DIR/image-build.log"
ACTIVATION_ENV="$EVIDENCE_DIR/activation.env"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "ERROR: another NEXOLAB deployment operation is running" >&2; exit 75; }

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$SUMMARY"
}

container_id() {
  docker inspect --format '{{.Id}}' "$1" 2>/dev/null
}

http_code() {
  curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "$1"
}

CORE_NAMES=(
  nexolab-central-postgres-1
  nexolab-central-mqtt-1
  nexolab-central-minio-1
  nexolab-central-telemetry-service-1
  nexolab-edge-device-agent-1
)
declare -A CORE_IDS=()
for name in "${CORE_NAMES[@]}"; do
  id="$(container_id "$name")" || { log "ERROR: required core container missing: $name"; exit 1; }
  CORE_IDS["$name"]="$id"
done
[[ "$(http_code http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard preflight failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:8082/health/ready)" == "200" ]] || { log "ERROR: Telemetry preflight failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:13021/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App frontend candidate unavailable"; exit 1; }

if docker ps -a --format '{{.Names}}' | grep -Fxq 'nexolab-central-telegram-gateway-1'; then
  log "ERROR: Telegram gateway already exists; Stage 1 expects a clean absent adapter"
  exit 1
fi

SERVE_HASH_BEFORE="$(tailscale serve status | sha256sum | awk '{print $1}')"
IMAGE_TAG="nexolab-telegram-gateway:tg04-${EXPECTED_SOURCE:0:12}"

cat >"$ACTIVATION_ENV" <<EOF
TELEGRAM_ENABLED=false
TELEGRAM_MINIAPP_ENABLED=true
TELEGRAM_GATEWAY_IMAGE=$IMAGE_TAG
EOF
chmod 0600 "$ACTIVATION_ENV"

COMPOSE=(
  docker compose
  --env-file "$CENTRAL_ENV"
  --env-file "$TELEGRAM_ENV"
  --env-file "$ACTIVATION_ENV"
  -f "$COMPOSE_DIR/compose.central.yaml"
  -f "$COMPOSE_DIR/compose.telegram.yaml"
  --profile telegram
)
rollback_on_exit() {
  rc=$?
  trap - EXIT
  if [[ "$SUCCESS" != "1" && "$STARTED" == "1" ]]; then
    log "Stage 1 failed; removing only the newly created Telegram gateway container"
    "${COMPOSE[@]}" rm -sf telegram-gateway >>"$SUMMARY" 2>&1 || true
  fi
  exit "$rc"
}
trap rollback_on_exit EXIT

log "TG-04 Stage 1 start: source=$EXPECTED_SOURCE"
log "Safety: Telegram delivery disabled; Mini App only; no core restart"

PYTHONPATH="$REPO_ROOT/services/telegram-gateway" \
  python3 -m app.runtime_secret_permissions >>"$SUMMARY"

"${COMPOSE[@]}" config --quiet

docker build \
  --tag "$IMAGE_TAG" \
  "$REPO_ROOT/services/telegram-gateway" >"$BUILD_LOG" 2>&1
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
[[ -n "$IMAGE_ID" ]] || { log "ERROR: gateway image identity unavailable"; exit 1; }
log "Gateway image built: $IMAGE_ID"

"${COMPOSE[@]}" up -d --no-deps --no-build telegram-gateway >>"$SUMMARY" 2>&1
STARTED="1"
for _ in $(seq 1 30); do
  HEALTH="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' nexolab-central-telegram-gateway-1 2>/dev/null || true)"
  [[ "$HEALTH" == "healthy" ]] && break
  [[ "$HEALTH" == "unhealthy" ]] && { log "ERROR: gateway became unhealthy"; exit 1; }
  sleep 2
done
[[ "${HEALTH:-}" == "healthy" ]] || { log "ERROR: gateway health timeout"; exit 1; }

GATEWAY_CONTAINER_IMAGE="$(docker inspect --format '{{.Image}}' nexolab-central-telegram-gateway-1)"
[[ "$GATEWAY_CONTAINER_IMAGE" == "$IMAGE_ID" ]] || { log "ERROR: gateway image mismatch"; exit 1; }

HEALTH_JSON="$EVIDENCE_DIR/gateway-health.json"
curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready >"$HEALTH_JSON"
python3 - "$HEALTH_JSON" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p.get('status') == 'ready', p
assert p.get('enabled') is True, p
assert p.get('delivery_enabled') is False, p
assert p.get('miniapp_enabled') is True, p
assert p.get('running') is False, p
PY
log "Gateway Mini App readiness: PASS (delivery=false miniapp=true worker=false)"
for name in "${CORE_NAMES[@]}"; do
  after="$(container_id "$name")" || { log "ERROR: core container disappeared: $name"; exit 1; }
  [[ "$after" == "${CORE_IDS[$name]}" ]] || { log "ERROR: core container identity changed: $name"; exit 1; }
done

[[ "$(http_code http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard post-check failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:8082/health/ready)" == "200" ]] || { log "ERROR: Telemetry post-check failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:13021/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App frontend changed unexpectedly"; exit 1; }
SERVE_HASH_AFTER="$(tailscale serve status | sha256sum | awk '{print $1}')"
[[ "$SERVE_HASH_AFTER" == "$SERVE_HASH_BEFORE" ]] || { log "ERROR: Tailscale Serve topology changed"; exit 1; }

log "Core container identities unchanged: PASS"
log "Dashboard/Telemetry/frontend candidate remained healthy: PASS"
log "Tailscale Serve topology unchanged: PASS"
log "No Telegram delivery worker started and no report send was requested"
log "Evidence: $EVIDENCE_DIR"
SUCCESS="1"
trap - EXIT
exit 0
