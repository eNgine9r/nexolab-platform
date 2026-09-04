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
LOCK_FILE="${NEXOLAB_TG04_REFRESH_LOCK_FILE:-/run/lock/nexolab-tg04-gateway-refresh.lock}"
GATEWAY_NAME="nexolab-central-telegram-gateway-1"
BOUNDARY_PROBE="$SCRIPT_DIR/telegram-gateway-boundary-runtime-proof.sh"
EXPECTED_SOURCE=""
EXPECTED_CURRENT_IMAGE_ID=""
EXPECTED_TARGET_IMAGE_ID=""
APPROVED="0"
MUTATED="0"
SUCCESS="0"

usage() {
  cat <<'USAGE'
Usage: deploy-telegram-gateway-refresh.sh \
  --expected-source-sha SHA \
  --expected-current-image-id sha256:... \
  --expected-target-image-id sha256:... \
  --approve-gateway-refresh

Refreshes only the persistent Telegram Gateway to one prebuilt, exact-source, behaviorally verified image. Delivery and scheduler remain disabled.
USAGE
}
while (($# > 0)); do
  case "$1" in
    --expected-source-sha)
      (($# >= 2)) || { echo "ERROR: --expected-source-sha requires SHA" >&2; exit 64; }
      EXPECTED_SOURCE="$2"
      shift 2
      ;;
    --expected-current-image-id)
      (($# >= 2)) || { echo "ERROR: --expected-current-image-id requires image ID" >&2; exit 64; }
      EXPECTED_CURRENT_IMAGE_ID="$2"
      shift 2
      ;;
    --expected-target-image-id)
      (($# >= 2)) || { echo "ERROR: --expected-target-image-id requires image ID" >&2; exit 64; }
      EXPECTED_TARGET_IMAGE_ID="$2"
      shift 2
      ;;
    --approve-gateway-refresh)
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
[[ "$EXPECTED_CURRENT_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: exact current image ID required" >&2; exit 64; }
[[ "$EXPECTED_TARGET_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: exact target image ID required" >&2; exit 64; }
[[ "$APPROVED" == "1" ]] || { echo "ERROR: explicit --approve-gateway-refresh is required" >&2; exit 64; }
[[ "$EUID" -eq 0 ]] || { echo "ERROR: root_required" >&2; exit 77; }
for command in git docker curl python3 flock sha256sum tailscale grep sed; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing command: $command" >&2; exit 69; }
done
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose unavailable" >&2; exit 69; }
[[ -f "$CENTRAL_ENV" && ! -L "$CENTRAL_ENV" ]] || { echo "ERROR: central env unavailable" >&2; exit 66; }
[[ -f "$TELEGRAM_ENV" && ! -L "$TELEGRAM_ENV" ]] || { echo "ERROR: protected Telegram env unavailable" >&2; exit 66; }
[[ -f "$COMPOSE_DIR/compose.central.yaml" && -f "$COMPOSE_DIR/compose.telegram.yaml" ]] \
  || { echo "ERROR: compose contract unavailable" >&2; exit 66; }
[[ -f "$BOUNDARY_PROBE" && ! -L "$BOUNDARY_PROBE" ]] \
  || { echo "ERROR: boundary probe unavailable" >&2; exit 66; }

python3 - "$TELEGRAM_ENV" <<'PYENV'
from pathlib import Path
import sys
lines=Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
values={}
counts={}
for raw in lines:
    line=raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key,value=line.split("=",1)
    key=key.strip(); value=value.strip()
    counts[key]=counts.get(key,0)+1
    values[key]=value
assert counts.get("TELEGRAM_ENABLED") == 1 and values.get("TELEGRAM_ENABLED") == "false"
thread=values.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID", "")
assert counts.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID") == 1
assert thread.isdigit() and int(thread) > 0
print("Protected Telegram env contract: PASS (delivery=false topic=present)")
PYENV

cd "$REPO_ROOT"
GIT=(git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT")
"${GIT[@]}" fetch --quiet origin main \
  || { echo "ERROR: unable to refresh origin/main authority" >&2; exit 69; }
ACTUAL_SOURCE="$("${GIT[@]}" rev-parse HEAD)"
[[ "$ACTUAL_SOURCE" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: source SHA mismatch" >&2; exit 65; }
REMOTE_MAIN="$("${GIT[@]}" rev-parse origin/main 2>/dev/null || true)"
[[ "$REMOTE_MAIN" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: expected source is not current origin/main" >&2; exit 65; }
[[ -z "$("${GIT[@]}" status --porcelain --untracked-files=all)" ]] \
  || { echo "ERROR: source worktree is not clean" >&2; exit 65; }

mkdir -p "$EVIDENCE_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/tg04-telegram-refresh-$STAMP"
mkdir -m 0700 "$EVIDENCE_DIR"
SUMMARY="$EVIDENCE_DIR/summary.txt"
ACTIVATION_ENV="$EVIDENCE_DIR/activation.env"
ROLLBACK_ENV="$EVIDENCE_DIR/rollback.env"
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

env_value() {
  local file="$1" key="$2" default="$3" value
  value="$(sed -n "s/^${key}=//p" "$file" | tail -n 1)"
  printf '%s' "${value:-$default}"
}

wait_gateway_healthy() {
  local health=""
  for _ in $(seq 1 30); do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$GATEWAY_NAME" 2>/dev/null || true)"
    [[ "$health" == "healthy" ]] && return 0
    [[ "$health" == "unhealthy" ]] && return 1
    sleep 2
  done
  return 1
}

gateway_safety_ready() {
  curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready \
    | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("status") == "ready", p
assert p.get("delivery_enabled") is False, p
assert p.get("miniapp_enabled") is True, p
assert p.get("running") is False, p
assert p.get("last_send_at") is None, p
' >/dev/null
}
CENTRAL_BIND="$(env_value "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS 127.0.0.1)"
CENTRAL_API_PORT="$(env_value "$CENTRAL_ENV" CENTRAL_API_PORT 8082)"
TELEMETRY_READY_URL="http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/health/ready"
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

container_id "$GATEWAY_NAME" >/dev/null \
  || { log "ERROR: persistent Telegram Gateway is missing"; exit 1; }
wait_gateway_healthy || { log "ERROR: existing Telegram Gateway is not healthy"; exit 1; }
gateway_safety_ready || { log "ERROR: existing Gateway safety boundary is not closed"; exit 1; }

OLD_CONTAINER_ID="$(container_id "$GATEWAY_NAME")"
OLD_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$GATEWAY_NAME")"
[[ "$OLD_IMAGE_ID" == "$EXPECTED_CURRENT_IMAGE_ID" ]] || { log "ERROR: current Gateway image changed since approval preparation"; exit 1; }
docker image inspect "$OLD_IMAGE_ID" >/dev/null 2>&1 \
  || { log "ERROR: previous Gateway image unavailable for rollback"; exit 1; }
[[ "$EXPECTED_TARGET_IMAGE_ID" != "$OLD_IMAGE_ID" ]] \
  || { log "ERROR: target Gateway image matches current image"; exit 1; }
docker image inspect "$EXPECTED_TARGET_IMAGE_ID" >/dev/null 2>&1 \
  || { log "ERROR: pre-approved target Gateway image is unavailable locally"; exit 1; }
EXPECTED_GATEWAY_TREE="$(git rev-parse "${EXPECTED_SOURCE}:services/telegram-gateway")"
TARGET_REVISION="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$EXPECTED_TARGET_IMAGE_ID" 2>/dev/null || true)"
TARGET_GATEWAY_TREE="$(docker image inspect --format '{{index .Config.Labels "io.nexolab.source-tree"}}' "$EXPECTED_TARGET_IMAGE_ID" 2>/dev/null || true)"
[[ "$TARGET_REVISION" == "$EXPECTED_SOURCE" ]] \
  || { log "ERROR: target Gateway image source revision mismatch"; exit 1; }
[[ "$TARGET_GATEWAY_TREE" == "$EXPECTED_GATEWAY_TREE" ]] \
  || { log "ERROR: target Gateway image source tree mismatch"; exit 1; }
bash "$BOUNDARY_PROBE" \
  --expected-source-sha "$EXPECTED_SOURCE" \
  --image-id "$EXPECTED_TARGET_IMAGE_ID" >>"$SUMMARY" \
  || { log "ERROR: target Gateway image lacks the approved bootstrap delivery boundary"; exit 1; }
log "Target Gateway image approval pin: PASS (exact image, exact source revision/tree, behavioral boundary)"
OUTBOX_VOLUME="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data/telegram-delivery"}}{{.Name}}{{end}}{{end}}' "$GATEWAY_NAME")"
[[ -n "$OUTBOX_VOLUME" ]] || { log "ERROR: Gateway delivery volume identity unavailable"; exit 1; }

docker inspect nexolab-central-telemetry-service-1 --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false' >/dev/null \
  || { log "ERROR: weekday scheduler must remain disabled"; exit 1; }
[[ "$(http_code http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard preflight failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:3000/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App preflight failed"; exit 1; }
[[ "$(http_code "$TELEMETRY_READY_URL")" == "200" ]] || { log "ERROR: Telemetry preflight failed"; exit 1; }
SERVE_HASH_BEFORE="$(tailscale serve status | sha256sum | awk '{print $1}')"
IMAGE_TAG="nexolab-telegram-gateway:tg04-refresh-${EXPECTED_SOURCE:0:12}"
ROLLBACK_IMAGE_TAG="nexolab-telegram-gateway:tg04-refresh-rollback-${EXPECTED_SOURCE:0:12}-${STAMP}"
docker tag "$OLD_IMAGE_ID" "$ROLLBACK_IMAGE_TAG"
cat >"$ACTIVATION_ENV" <<EOF
TELEGRAM_ENABLED=false
TELEGRAM_MINIAPP_ENABLED=true
TELEGRAM_GATEWAY_IMAGE=$IMAGE_TAG
TELEGRAM_GATEWAY_SECRETS_DIR=$SECRET_DIR
EOF
cat >"$ROLLBACK_ENV" <<EOF
TELEGRAM_ENABLED=false
TELEGRAM_MINIAPP_ENABLED=true
TELEGRAM_GATEWAY_IMAGE=$ROLLBACK_IMAGE_TAG
TELEGRAM_GATEWAY_SECRETS_DIR=$SECRET_DIR
EOF
chmod 0600 "$ACTIVATION_ENV" "$ROLLBACK_ENV"

COMPOSE=(
  docker compose
  --env-file "$CENTRAL_ENV"
  --env-file "$TELEGRAM_ENV"
  -f "$COMPOSE_DIR/compose.central.yaml"
  -f "$COMPOSE_DIR/compose.telegram.yaml"
  --profile telegram
)

rollback_on_exit() {
  rc=$?
  trap - EXIT
  if [[ "$SUCCESS" != "1" && "$MUTATED" == "1" ]]; then
    log "Refresh failed; restoring previous Telegram Gateway image with delivery disabled"
    if "${COMPOSE[@]}" --env-file "$ROLLBACK_ENV" up -d --no-deps --no-build --force-recreate telegram-gateway >>"$SUMMARY" 2>&1; then
      if wait_gateway_healthy \
        && [[ "$(docker inspect --format '{{.Image}}' "$GATEWAY_NAME" 2>/dev/null || true)" == "$OLD_IMAGE_ID" ]] \
        && [[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data/telegram-delivery"}}{{.Name}}{{end}}{{end}}' "$GATEWAY_NAME" 2>/dev/null || true)" == "$OUTBOX_VOLUME" ]] \
        && gateway_safety_ready; then
        log "Rollback verification: PASS (previous image, delivery volume and safety boundary restored)"
      else
        log "WARNING: rollback completed but full Gateway rollback verification failed"
      fi
    else
      log "WARNING: rollback Gateway recreation failed"
    fi
  fi
  exit "$rc"
}
trap rollback_on_exit EXIT

log "TG-04 Gateway refresh start: source=$EXPECTED_SOURCE"
log "Safety: delivery=false miniapp=true scheduler=false; only Telegram Gateway may recreate"
PYTHONPATH="$REPO_ROOT/services/telegram-gateway" \
  python3 -m app.runtime_secret_permissions --secret-dir "$SECRET_DIR" >>"$SUMMARY"

"${COMPOSE[@]}" --env-file "$ACTIVATION_ENV" config --quiet

docker tag "$EXPECTED_TARGET_IMAGE_ID" "$IMAGE_TAG"
IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"
[[ "$IMAGE_ID" == "$EXPECTED_TARGET_IMAGE_ID" ]] \
  || { log "ERROR: approved target Gateway image tag mismatch"; exit 1; }
log "Approved target Gateway image prepared: $IMAGE_ID"

MUTATED="1"
"${COMPOSE[@]}" --env-file "$ACTIVATION_ENV" \
  up -d --no-deps --no-build --force-recreate telegram-gateway >>"$SUMMARY" 2>&1
wait_gateway_healthy || { log "ERROR: refreshed Gateway did not become healthy"; exit 1; }

NEW_CONTAINER_ID="$(container_id "$GATEWAY_NAME")"
[[ "$NEW_CONTAINER_ID" != "$OLD_CONTAINER_ID" ]] || { log "ERROR: Gateway container was not recreated"; exit 1; }
NEW_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$GATEWAY_NAME")"
[[ "$NEW_IMAGE_ID" == "$IMAGE_ID" ]] || { log "ERROR: refreshed Gateway image mismatch"; exit 1; }
NEW_OUTBOX_VOLUME="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data/telegram-delivery"}}{{.Name}}{{end}}{{end}}' "$GATEWAY_NAME")"
[[ "$NEW_OUTBOX_VOLUME" == "$OUTBOX_VOLUME" ]] || { log "ERROR: Gateway delivery volume identity changed"; exit 1; }

docker inspect "$GATEWAY_NAME" | python3 -c '
import json,sys
p=json.load(sys.stdin)[0]
env=dict(item.split("=",1) for item in p["Config"]["Env"] if "=" in item)
assert env.get("TELEGRAM_ENABLED") == "false"
assert env.get("TELEGRAM_MINIAPP_ENABLED") == "true"
thread=env.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID", "")
assert thread.isdigit() and int(thread) > 0
print("Gateway runtime env contract: PASS (delivery=false miniapp=true topic=present)")
' >>"$SUMMARY"
HEALTH_JSON="$EVIDENCE_DIR/gateway-health.json"
curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready >"$HEALTH_JSON"
python3 - "$HEALTH_JSON" <<'PY'
import json, sys
p=json.load(open(sys.argv[1], encoding='utf-8'))
assert p.get('status') == 'ready', p
assert p.get('delivery_enabled') is False, p
assert p.get('miniapp_enabled') is True, p
assert p.get('running') is False, p
assert p.get('last_send_at') is None, p
PY
log "Gateway readiness: PASS (delivery=false miniapp=true worker=false last_send=null)"

for name in "${CORE_NAMES[@]}"; do
  after="$(container_id "$name")" || { log "ERROR: core container disappeared: $name"; exit 1; }
  [[ "$after" == "${CORE_IDS[$name]}" ]] || { log "ERROR: core container identity changed: $name"; exit 1; }
done

docker inspect nexolab-central-telemetry-service-1 --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false' >/dev/null \
  || { log "ERROR: weekday scheduler changed unexpectedly"; exit 1; }
[[ "$(http_code http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard post-check failed"; exit 1; }
[[ "$(http_code http://127.0.0.1:3000/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App post-check failed"; exit 1; }
[[ "$(http_code "$TELEMETRY_READY_URL")" == "200" ]] || { log "ERROR: Telemetry post-check failed"; exit 1; }
SERVE_HASH_AFTER="$(tailscale serve status | sha256sum | awk '{print $1}')"
[[ "$SERVE_HASH_AFTER" == "$SERVE_HASH_BEFORE" ]] || { log "ERROR: Tailscale Serve topology changed"; exit 1; }

log "Gateway delivery volume identity unchanged: PASS"
log "Core container identities unchanged: PASS"
log "Dashboard/Telemetry/Mini App remained healthy: PASS"
log "Tailscale Serve topology unchanged: PASS"
log "No Telegram delivery worker started and no report send was requested"
log "Previous Gateway image retained for rollback: $OLD_IMAGE_ID"
log "Evidence: $EVIDENCE_DIR"
SUCCESS="1"
trap - EXIT
exit 0
