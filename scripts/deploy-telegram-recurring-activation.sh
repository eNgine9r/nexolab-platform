#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/infrastructure/compose"
CENTRAL_ENV="${NEXOLAB_CENTRAL_ENV:-$COMPOSE_DIR/.env.central}"
SECRET_DIR="${NEXOLAB_TELEGRAM_SECRET_DIR:-/etc/nexolab/telegram}"
TELEGRAM_ENV="$SECRET_DIR/telegram.env"
LOCAL_AUTH_OVERLAY="$COMPOSE_DIR/compose.local-auth.yaml"
OBSERVABILITY_OVERLAY="$COMPOSE_DIR/compose.observability.yaml"
PLAN_SCRIPT="$REPO_ROOT/scripts/tg04-recurring-activation-runtime-plan.py"
EVIDENCE_ROOT="${NEXOLAB_TG04_EVIDENCE_ROOT:-$REPO_ROOT/runtime/evidence}"
LOCK_FILE="${NEXOLAB_TG04_ACTIVATION_LOCK_FILE:-/run/lock/nexolab-tg04-recurring-activation.lock}"
GATEWAY_REFRESH_LOCK_FILE="${NEXOLAB_TG04_REFRESH_LOCK_FILE:-/run/lock/nexolab-tg04-gateway-refresh.lock}"
STAGE1_LOCK_FILE="${NEXOLAB_TG04_LOCK_FILE:-/run/lock/nexolab-tg04-stage1.lock}"
CURRENT_HEAD_LOCK_NAME="nexolab-current-head-launch.lock"
TELEMETRY_NAME="nexolab-central-telemetry-service-1"
GATEWAY_NAME="nexolab-central-telegram-gateway-1"
EXPECTED_SOURCE=""
EXPECTED_TELEMETRY_IMAGE_ID=""
EXPECTED_GATEWAY_IMAGE_ID=""
EXPECTED_IMMEDIATE=""
APPROVED="0"
MUTATED="0"
SUCCESS="0"
ROLLBACK_ROOT=""
ROLLBACK_PROVEN="0"

usage() {
  cat <<'USAGE'
Usage: deploy-telegram-recurring-activation.sh \
  --expected-source-sha SHA \
  --expected-current-telemetry-image-id sha256:... \
  --expected-current-gateway-image-id sha256:... \
  --approve-immediate-deliveries N \
  --approve-recurring-activation

Activates the accepted TestLAB Europe/Kyiv Mon-Fri 07:50 scheduler and exact forum-topic delivery.
USAGE
}

while (($# > 0)); do
  case "$1" in
    --expected-source-sha)
      (($# >= 2)) || { echo "ERROR: --expected-source-sha requires SHA" >&2; exit 64; }
      EXPECTED_SOURCE="$2"; shift 2 ;;
    --expected-current-telemetry-image-id)
      (($# >= 2)) || { echo "ERROR: --expected-current-telemetry-image-id requires image ID" >&2; exit 64; }
      EXPECTED_TELEMETRY_IMAGE_ID="$2"; shift 2 ;;
    --expected-current-gateway-image-id)
      (($# >= 2)) || { echo "ERROR: --expected-current-gateway-image-id requires image ID" >&2; exit 64; }
      EXPECTED_GATEWAY_IMAGE_ID="$2"; shift 2 ;;
    --approve-immediate-deliveries)
      (($# >= 2)) || { echo "ERROR: --approve-immediate-deliveries requires count" >&2; exit 64; }
      EXPECTED_IMMEDIATE="$2"; shift 2 ;;
    --approve-recurring-activation)
      APPROVED="1"; shift ;;
    --help|-h)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done

[[ "$EXPECTED_SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo "ERROR: exact lowercase source SHA required" >&2; exit 64; }
[[ "$EXPECTED_TELEMETRY_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: exact Telemetry image ID required" >&2; exit 64; }
[[ "$EXPECTED_GATEWAY_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "ERROR: exact Gateway image ID required" >&2; exit 64; }
[[ "$EXPECTED_IMMEDIATE" =~ ^[0-9]+$ ]] || { echo "ERROR: exact non-negative immediate delivery count required" >&2; exit 64; }
[[ "$APPROVED" == "1" ]] || { echo "ERROR: explicit --approve-recurring-activation is required" >&2; exit 64; }
[[ "$EUID" -eq 0 ]] || { echo "ERROR: root_required" >&2; exit 77; }

for command in git docker curl python3 flock sha256sum tailscale grep sed cp cmp rm seq awk date tee dirname; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing command: $command" >&2; exit 69; }
done
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose unavailable" >&2; exit 69; }
[[ -x "$PLAN_SCRIPT" ]] || { echo "ERROR: activation planner unavailable" >&2; exit 66; }
[[ -f "$CENTRAL_ENV" && ! -L "$CENTRAL_ENV" ]] || { echo "ERROR: central env unavailable" >&2; exit 66; }
[[ -f "$TELEGRAM_ENV" && ! -L "$TELEGRAM_ENV" ]] || { echo "ERROR: protected Telegram env unavailable" >&2; exit 66; }
[[ -f "$COMPOSE_DIR/compose.central.yaml" && -f "$OBSERVABILITY_OVERLAY" && -f "$COMPOSE_DIR/compose.telegram.yaml" ]] \
  || { echo "ERROR: compose contract unavailable" >&2; exit 66; }

python3 - "$CENTRAL_ENV" "$TELEGRAM_ENV" <<'PYENV'
from pathlib import Path
import sys

def parse(path: Path):
    st=path.lstat()
    if not path.is_file() or path.is_symlink() or st.st_nlink != 1:
        raise SystemExit("unsafe_runtime_env")
    values={}; counts={}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.split("=",1); key=key.strip(); value=value.strip()
        counts[key]=counts.get(key,0)+1; values[key]=value
    return values,counts
central,cc=parse(Path(sys.argv[1])); telegram,tc=parse(Path(sys.argv[2]))
assert cc.get("DAILY_REPORTS_SCHEDULER_ENABLED",0) <= 1
assert central.get("DAILY_REPORTS_SCHEDULER_ENABLED","false") == "false"
assert tc.get("TELEGRAM_ENABLED") == 1 and telegram.get("TELEGRAM_ENABLED") == "false"
assert tc.get("TELEGRAM_MINIAPP_ENABLED") == 1 and telegram.get("TELEGRAM_MINIAPP_ENABLED") in {"false","true"}
thread=telegram.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID","")
assert tc.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID") == 1 and thread.isdigit() and int(thread) > 0
print("Persistent activation flags: PASS (scheduler=false delivery=false topic=present)")
PYENV

cd "$REPO_ROOT"
GIT=(git -c safe.directory="$REPO_ROOT" -C "$REPO_ROOT")
ACTUAL_SOURCE="$("${GIT[@]}" rev-parse HEAD)"
[[ "$ACTUAL_SOURCE" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: source SHA mismatch" >&2; exit 65; }
REMOTE_MAIN="$("${GIT[@]}" rev-parse origin/main 2>/dev/null || true)"
[[ "$REMOTE_MAIN" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: expected source is not current origin/main" >&2; exit 65; }
[[ -z "$("${GIT[@]}" status --porcelain --untracked-files=all)" ]] || { echo "ERROR: source worktree is not clean" >&2; exit 65; }

declare -a MUTATION_LOCK_FDS=()
declare -A MUTATION_LOCK_PATHS=()
acquire_mutation_lock() {
  local path="$1" fd parent
  [[ -n "${MUTATION_LOCK_PATHS[$path]+present}" ]] && return 0
  parent="$(dirname "$path")"
  [[ -d "$parent" ]] || { echo "ERROR: mutation lock directory unavailable: $parent" >&2; exit 75; }
  exec {fd}>"$path" || { echo "ERROR: cannot open mutation lock" >&2; exit 75; }
  if ! flock -n "$fd"; then
    eval "exec ${fd}>&-"
    echo "ERROR: another NEXOLAB deployment operation is running" >&2
    exit 75
  fi
  MUTATION_LOCK_FDS+=("$fd")
  MUTATION_LOCK_PATHS["$path"]="1"
}

ensure_invoking_user_lock_file() {
  local path="$1" uid="$2" gid="$3" parent
  parent="$(dirname "$path")"
  [[ -d "$parent" ]] || { echo "ERROR: invoking-user lock directory unavailable: $parent" >&2; exit 75; }
  python3 - "$path" "$uid" "$gid" <<'PYLOCK'
from pathlib import Path
import os, stat, sys
path=Path(sys.argv[1]); uid=int(sys.argv[2]); gid=int(sys.argv[3])
try:
    fd=os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
except FileExistsError:
    fd=None
if fd is not None:
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, 0o600)
        os.fsync(fd)
    finally:
        os.close(fd)
st=path.lstat()
if path.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
    raise SystemExit("unsafe_current_head_lock")
if st.st_uid != uid or st.st_gid != gid or not (stat.S_IMODE(st.st_mode) & stat.S_IWUSR):
    raise SystemExit("unexpected_current_head_lock_ownership")
PYLOCK
}

[[ "${SUDO_UID:-}" =~ ^[0-9]+$ && "${SUDO_GID:-}" =~ ^[0-9]+$ ]]   || { echo "ERROR: invoking sudo user identity is required for shared deployment locks" >&2; exit 77; }
USER_TMP_CURRENT_HEAD_LOCK="/tmp/$CURRENT_HEAD_LOCK_NAME"
USER_RUNTIME_CURRENT_HEAD_LOCK="/run/user/$SUDO_UID/$CURRENT_HEAD_LOCK_NAME"
ensure_invoking_user_lock_file "$USER_TMP_CURRENT_HEAD_LOCK" "$SUDO_UID" "$SUDO_GID"
[[ -d "/run/user/$SUDO_UID" ]]   || { echo "ERROR: invoking-user runtime lock directory unavailable" >&2; exit 75; }
ensure_invoking_user_lock_file "$USER_RUNTIME_CURRENT_HEAD_LOCK" "$SUDO_UID" "$SUDO_GID"

acquire_mutation_lock "$LOCK_FILE"
acquire_mutation_lock "$GATEWAY_REFRESH_LOCK_FILE"
acquire_mutation_lock "$STAGE1_LOCK_FILE"
acquire_mutation_lock "$USER_TMP_CURRENT_HEAD_LOCK"
acquire_mutation_lock "$USER_RUNTIME_CURRENT_HEAD_LOCK"

# Re-check source only after all known production mutation locks are held.
ACTUAL_SOURCE="$("${GIT[@]}" rev-parse HEAD)"
[[ "$ACTUAL_SOURCE" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: source SHA changed before locked baseline" >&2; exit 65; }
REMOTE_MAIN="$("${GIT[@]}" rev-parse origin/main 2>/dev/null || true)"
[[ "$REMOTE_MAIN" == "$EXPECTED_SOURCE" ]] || { echo "ERROR: origin/main changed before locked baseline" >&2; exit 65; }
[[ -z "$("${GIT[@]}" status --porcelain --untracked-files=all)" ]] || { echo "ERROR: source worktree changed before locked baseline" >&2; exit 65; }

mkdir -p "$EVIDENCE_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$EVIDENCE_ROOT/tg04-recurring-activation-$STAMP"
mkdir -m 0700 "$EVIDENCE_DIR"
SUMMARY="$EVIDENCE_DIR/summary.txt"
PLAN_BEFORE_FILE="$EVIDENCE_DIR/plan-before.json"
PLAN_AFTER_SCHEDULER_FILE="$EVIDENCE_DIR/plan-after-scheduler.json"
PLAN_AFTER_DELIVERY_FILE="$EVIDENCE_DIR/plan-after-delivery.json"
PIN_ENV="$EVIDENCE_DIR/image-pins.env"
ROLLBACK_OVERRIDE_ENV="$EVIDENCE_DIR/rollback-overrides.env"

log() { printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" | tee -a "$SUMMARY"; }
container_id() { docker inspect --format '{{.Id}}' "$1" 2>/dev/null; }
image_id() { docker inspect --format '{{.Image}}' "$1" 2>/dev/null; }
wait_healthy() {
  local name="$1" health=""
  for _ in $(seq 1 45); do
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || true)"
    [[ "$health" == "healthy" ]] && return 0
    [[ "$health" == "unhealthy" ]] && return 1
    sleep 2
  done
  return 1
}
env_value() {
  local file="$1" key="$2" default="$3" value
  value="$(sed -n "s/^${key}=//p" "$file" | tail -n 1)"
  printf '%s' "${value:-$default}"
}
resolve_compose_path() {
  local value="$1"
  if [[ "$value" == /* ]]; then
    printf '%s\n' "$value"
  else
    printf '%s/%s\n' "$COMPOSE_DIR" "$value"
  fi
}
json_field() {
  local key="$1"
  python3 -c 'import json,sys; v=json.load(sys.stdin)[sys.argv[1]]; print("true" if v is True else "false" if v is False else "" if v is None else v)' "$key"
}
set_env_values() {
  local path="$1"; shift
  python3 - "$path" "$@" <<'PYSET'
from pathlib import Path
import os, stat, sys
path=Path(sys.argv[1]); args=sys.argv[2:]
if len(args)%2: raise SystemExit("invalid_env_update")
updates=dict(zip(args[0::2],args[1::2]))
st=path.lstat()
if not path.is_file() or path.is_symlink() or st.st_nlink != 1: raise SystemExit("unsafe_env_target")
lines=path.read_text(encoding="utf-8").splitlines(); counts={key:0 for key in updates}; out=[]
for raw in lines:
    key=raw.split("=",1)[0].strip() if "=" in raw else ""
    if key in updates:
        counts[key]+=1
        if counts[key] > 1: raise SystemExit("duplicate_env_key")
        out.append(f"{key}={updates[key]}")
    else: out.append(raw)
for key,value in updates.items():
    if counts[key] == 0: out.append(f"{key}={value}")
tmp=path.with_name(f".{path.name}.tg04-{os.getpid()}")
fd=os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, stat.S_IMODE(st.st_mode))
try:
    os.fchown(fd, st.st_uid, st.st_gid); os.fchmod(fd, stat.S_IMODE(st.st_mode))
    with os.fdopen(fd,"w",encoding="utf-8") as stream:
        stream.write("\n".join(out)+"\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp,path)
    dfd=os.open(path.parent, os.O_RDONLY); os.fsync(dfd); os.close(dfd)
finally:
    if tmp.exists(): tmp.unlink()
PYSET
}
restore_file() {
  local backup="$1" target="$2"
  python3 - "$backup" "$target" <<'PYRESTORE'
from pathlib import Path
import os, stat, sys
src=Path(sys.argv[1]); dst=Path(sys.argv[2]); st=src.stat(); data=src.read_bytes()
tmp=dst.with_name(f".{dst.name}.restore-{os.getpid()}")
fd=os.open(tmp, os.O_WRONLY|os.O_CREAT|os.O_EXCL, stat.S_IMODE(st.st_mode))
try:
    os.fchown(fd,st.st_uid,st.st_gid); os.fchmod(fd,stat.S_IMODE(st.st_mode))
    with os.fdopen(fd,"wb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.replace(tmp,dst)
    dfd=os.open(dst.parent,os.O_RDONLY); os.fsync(dfd); os.close(dfd)
finally:
    if tmp.exists(): tmp.unlink()
PYRESTORE
}

persistent_flags_disabled_ready() {
  python3 - "$CENTRAL_ENV" "$TELEGRAM_ENV" <<'PYPERSIST'
from pathlib import Path
import sys

def parse(path):
    values={}; counts={}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line=raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key,value=line.split("=",1); key=key.strip(); value=value.strip()
        counts[key]=counts.get(key,0)+1; values[key]=value
    return values,counts
central,cc=parse(sys.argv[1]); telegram,tc=parse(sys.argv[2])
assert cc.get("DAILY_REPORTS_SCHEDULER_ENABLED",0) <= 1
assert central.get("DAILY_REPORTS_SCHEDULER_ENABLED","false") == "false"
assert tc.get("TELEGRAM_ENABLED") == 1
assert telegram.get("TELEGRAM_ENABLED") == "false"
PYPERSIST
}

gateway_disabled_ready() {
  curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("status")=="ready" and p.get("delivery_enabled") is False
assert p.get("miniapp_enabled") is True and p.get("running") is False
assert p.get("last_send_at") is None
' >/dev/null
}
gateway_enabled_ready() {
  curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready | python3 -c '
import json,sys
p=json.load(sys.stdin)
assert p.get("status")=="ready" and p.get("delivery_enabled") is True
assert p.get("miniapp_enabled") is True and p.get("running") is True
' >/dev/null
}
telemetry_local_auth_ready() {
  [[ "$LOCAL_AUTH_OVERLAY_ENABLED" != "true" ]] && return 0
  docker inspect "$TELEMETRY_NAME" | python3 -c '
import json,sys
p=json.load(sys.stdin)[0]
env=dict(item.split("=",1) for item in p["Config"]["Env"] if "=" in item)
assert env.get("AUTH_MODE")=="jwt"
assert env.get("AUTH_LOCAL_ENABLED")=="true"
destinations={mount.get("Destination") for mount in p.get("Mounts",[])}
assert "/run/secrets/nexolab_local_auth_private_key" in destinations
assert "/run/secrets/nexolab_local_auth_public_key" in destinations
' >/dev/null
}
telemetry_scheduler_disabled_ready() {
  docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false' >/dev/null
}
telemetry_observability_ready() {
  local runtime_version
  runtime_version="$(docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | sed -n 's/^NEXOLAB_TELEMETRY_VERSION=//p' | tail -n 1)"
  [[ -n "$CURRENT_TELEMETRY_VERSION" && "$runtime_version" == "$CURRENT_TELEMETRY_VERSION" ]] || return 1
  curl -fsS --max-time 5 "http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/metrics" \
    | grep -Fq 'nexolab_telemetry_build_info'
}

for name in "$TELEMETRY_NAME" "$GATEWAY_NAME"; do
  container_id "$name" >/dev/null || { log "ERROR: required service missing: $name"; exit 1; }
  wait_healthy "$name" || { log "ERROR: service not healthy before activation: $name"; exit 1; }
done
gateway_disabled_ready || { log "ERROR: Gateway safety boundary is not closed"; exit 1; }
OLD_TELEMETRY_CONTAINER_ID="$(container_id "$TELEMETRY_NAME")"
OLD_GATEWAY_CONTAINER_ID="$(container_id "$GATEWAY_NAME")"
OLD_TELEMETRY_IMAGE_ID="$(image_id "$TELEMETRY_NAME")"
OLD_GATEWAY_IMAGE_ID="$(image_id "$GATEWAY_NAME")"
[[ "$OLD_TELEMETRY_IMAGE_ID" == "$EXPECTED_TELEMETRY_IMAGE_ID" ]] || { log "ERROR: Telemetry image changed since approval preparation"; exit 1; }
[[ "$OLD_GATEWAY_IMAGE_ID" == "$EXPECTED_GATEWAY_IMAGE_ID" ]] || { log "ERROR: Gateway image changed since approval preparation"; exit 1; }
OUTBOX_VOLUME="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data/telegram-delivery"}}{{.Name}}{{end}}{{end}}' "$GATEWAY_NAME")"
[[ -n "$OUTBOX_VOLUME" ]] || { log "ERROR: Gateway outbox volume unavailable"; exit 1; }
docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=false' >/dev/null \
  || { log "ERROR: Telemetry scheduler must be disabled before activation"; exit 1; }

LOCAL_AUTH_COMPOSE_ARGS=()
LOCAL_AUTH_OVERLAY_ENABLED="false"
CURRENT_AUTH_LOCAL_ENABLED="$(docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^AUTH_LOCAL_ENABLED=//p' | tail -n 1)"
CURRENT_AUTH_MODE="$(docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^AUTH_MODE=//p' | tail -n 1)"
if [[ "$CURRENT_AUTH_LOCAL_ENABLED" == "true" ]]; then
  [[ "$CURRENT_AUTH_MODE" == "jwt" ]] || { log "ERROR: active local auth requires AUTH_MODE=jwt"; exit 1; }
  [[ -f "$LOCAL_AUTH_OVERLAY" ]] || { log "ERROR: active local-auth Compose overlay is missing"; exit 1; }
  LOCAL_PRIVATE="$(env_value "$CENTRAL_ENV" AUTH_LOCAL_PRIVATE_KEY_HOST_FILE '')"
  LOCAL_PUBLIC="$(env_value "$CENTRAL_ENV" AUTH_LOCAL_PUBLIC_KEY_HOST_FILE '')"
  [[ -n "$LOCAL_PRIVATE" && -n "$LOCAL_PUBLIC" ]] || { log "ERROR: active local auth key paths are missing"; exit 1; }
  [[ -r "$(resolve_compose_path "$LOCAL_PRIVATE")" && -r "$(resolve_compose_path "$LOCAL_PUBLIC")" ]] \
    || { log "ERROR: active local auth key files are unreadable"; exit 1; }
  LOCAL_AUTH_COMPOSE_ARGS=( -f "$LOCAL_AUTH_OVERLAY" )
  LOCAL_AUTH_OVERLAY_ENABLED="true"
  log "Local operator authentication overlay: PASS (active and preserved)"
elif [[ -n "$CURRENT_AUTH_LOCAL_ENABLED" && "$CURRENT_AUTH_LOCAL_ENABLED" != "false" ]]; then
  log "ERROR: unexpected AUTH_LOCAL_ENABLED value in current Telemetry runtime"; exit 1
fi
telemetry_local_auth_ready || { log "ERROR: current Telemetry local-auth runtime contract is incomplete"; exit 1; }
CURRENT_TELEMETRY_VERSION="$(docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^NEXOLAB_TELEMETRY_VERSION=//p' | tail -n 1)"
TARGET_TELEMETRY_VERSION="$(env_value "$CENTRAL_ENV" NEXOLAB_TELEMETRY_VERSION 0.15.0)"
[[ -n "$CURRENT_TELEMETRY_VERSION" && "$CURRENT_TELEMETRY_VERSION" == "$TARGET_TELEMETRY_VERSION" ]] \
  || { log "ERROR: active Telemetry observability version contract would change during recreation"; exit 1; }

CORE_NAMES=(nexolab-central-postgres-1 nexolab-central-mqtt-1 nexolab-central-minio-1 nexolab-edge-device-agent-1)
declare -A CORE_IDS=()
for name in "${CORE_NAMES[@]}"; do
  id="$(container_id "$name")" || { log "ERROR: required core container missing: $name"; exit 1; }
  CORE_IDS["$name"]="$id"
done
CENTRAL_BIND="$(env_value "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS 127.0.0.1)"
CENTRAL_API_PORT="$(env_value "$CENTRAL_ENV" CENTRAL_API_PORT 8082)"
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard preflight failed"; exit 1; }
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3000/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App preflight failed"; exit 1; }
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/health/ready")" == "200" ]] || { log "ERROR: Telemetry preflight failed"; exit 1; }
telemetry_observability_ready || { log "ERROR: current Telemetry observability runtime contract is incomplete"; exit 1; }
SERVE_HASH_BEFORE="$(tailscale serve status | sha256sum | awk '{print $1}')"

PLAN_BEFORE="$($PLAN_SCRIPT)" || { log "ERROR: recurring activation planner failed"; exit 1; }
printf '%s\n' "$PLAN_BEFORE" >"$PLAN_BEFORE_FILE"
PLAN_IMMEDIATE="$(printf '%s' "$PLAN_BEFORE" | json_field predicted_immediate_delivery_count)"
PLAN_GENERATION="$(printf '%s' "$PLAN_BEFORE" | json_field predicted_snapshot_generation_count)"
SNAPSHOTS_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field snapshot_total_count)"
OUTBOX_ROWS_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_rows)"
OUTBOX_MAX_ID_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_max_id)"
OUTBOX_FINGERPRINT_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_fingerprint)"
OUTBOX_NON_SENT_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_non_sent_rows)"
OUTBOX_DUP_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_duplicate_risk_rows)"
TOPIC_SENT_BEFORE="$(printf '%s' "$PLAN_BEFORE" | json_field outbox_topic_sent_rows)"
[[ "$OUTBOX_ROWS_BEFORE" == "2" && "$OUTBOX_NON_SENT_BEFORE" == "0" && "$OUTBOX_DUP_BEFORE" == "0" && "$TOPIC_SENT_BEFORE" == "1" ]] \
  || { log "ERROR: historical outbox baseline is not the accepted two-row state"; exit 1; }
[[ "$SNAPSHOTS_BEFORE" == "1" ]] || { log "ERROR: persisted snapshot baseline changed; new Product Owner review required"; exit 1; }
[[ "$PLAN_IMMEDIATE" == "$EXPECTED_IMMEDIATE" ]] || { log "ERROR: approved immediate delivery count does not match current plan"; exit 1; }
log "Activation plan: PASS (predicted_snapshot_generation=$PLAN_GENERATION predicted_immediate_deliveries=$PLAN_IMMEDIATE)"

ROLLBACK_ROOT="/run/nexolab-tg04-recurring-$STAMP"
mkdir -m 0700 "$ROLLBACK_ROOT"
cp --preserve=mode,ownership,timestamps "$CENTRAL_ENV" "$ROLLBACK_ROOT/central.env"
cp --preserve=mode,ownership,timestamps "$TELEGRAM_ENV" "$ROLLBACK_ROOT/telegram.env"
TELEMETRY_PIN_TAG="nexolab-telemetry-service:tg04-recurring-pin-${EXPECTED_SOURCE:0:12}"
GATEWAY_PIN_TAG="nexolab-telegram-gateway:tg04-recurring-pin-${EXPECTED_SOURCE:0:12}"
docker tag "$OLD_TELEMETRY_IMAGE_ID" "$TELEMETRY_PIN_TAG"
docker tag "$OLD_GATEWAY_IMAGE_ID" "$GATEWAY_PIN_TAG"
cat >"$PIN_ENV" <<EOF
TELEMETRY_SERVICE_IMAGE=$TELEMETRY_PIN_TAG
TELEGRAM_GATEWAY_IMAGE=$GATEWAY_PIN_TAG
EOF
cat >"$ROLLBACK_OVERRIDE_ENV" <<EOF
TELEMETRY_SERVICE_IMAGE=$TELEMETRY_PIN_TAG
TELEGRAM_GATEWAY_IMAGE=$GATEWAY_PIN_TAG
DAILY_REPORTS_SCHEDULER_ENABLED=false
TELEGRAM_ENABLED=false
TELEGRAM_MINIAPP_ENABLED=true
EOF
chmod 0600 "$PIN_ENV" "$ROLLBACK_OVERRIDE_ENV"

COMPOSE=(docker compose --env-file "$CENTRAL_ENV" --env-file "$TELEGRAM_ENV" -f "$COMPOSE_DIR/compose.central.yaml" -f "$OBSERVABILITY_OVERLAY" "${LOCAL_AUTH_COMPOSE_ARGS[@]}" -f "$COMPOSE_DIR/compose.telegram.yaml" --profile telegram)
"${COMPOSE[@]}" --env-file "$PIN_ENV" config --quiet >/dev/null
log "Compose activation model: PASS (observability=true local_auth_overlay=$LOCAL_AUTH_OVERLAY_ENABLED)"

rollback_on_exit() {
  rc=$?
  trap - EXIT
  if [[ "$SUCCESS" != "1" && "$MUTATED" == "1" ]]; then
    log "Activation failed; disabling recurring delivery and restoring previous runtime config/images"
    CENTRAL_RESTORE_OK="0"
    TELEGRAM_RESTORE_OK="0"
    PERSISTENT_ROLLBACK_OK="0"
    if restore_file "$ROLLBACK_ROOT/central.env" "$CENTRAL_ENV" \
      && cmp -s "$ROLLBACK_ROOT/central.env" "$CENTRAL_ENV"; then
      CENTRAL_RESTORE_OK="1"
    fi
    if restore_file "$ROLLBACK_ROOT/telegram.env" "$TELEGRAM_ENV" \
      && cmp -s "$ROLLBACK_ROOT/telegram.env" "$TELEGRAM_ENV"; then
      TELEGRAM_RESTORE_OK="1"
    fi
    if [[ "$CENTRAL_RESTORE_OK" == "1" && "$TELEGRAM_RESTORE_OK" == "1" ]] \
      && persistent_flags_disabled_ready; then
      PERSISTENT_ROLLBACK_OK="1"
    fi
    TELEMETRY_ROLLBACK_OK="0"
    if "${COMPOSE[@]}" --env-file "$ROLLBACK_OVERRIDE_ENV" up -d --no-deps --no-build --force-recreate telemetry-service >>"$SUMMARY" 2>&1 \
      && wait_healthy "$TELEMETRY_NAME" \
      && telemetry_scheduler_disabled_ready \
      && telemetry_local_auth_ready \
      && telemetry_observability_ready; then
      TELEMETRY_ROLLBACK_OK="1"
    fi
    GATEWAY_ROLLBACK_OK="0"
    if "${COMPOSE[@]}" --env-file "$ROLLBACK_OVERRIDE_ENV" up -d --no-deps --no-build --force-recreate telegram-gateway >>"$SUMMARY" 2>&1 \
      && wait_healthy "$GATEWAY_NAME" \
      && gateway_disabled_ready; then
      GATEWAY_ROLLBACK_OK="1"
    fi
    if [[ "$PERSISTENT_ROLLBACK_OK" == "1" && "$TELEMETRY_ROLLBACK_OK" == "1" && "$GATEWAY_ROLLBACK_OK" == "1" ]]; then
      ROLLBACK_PROVEN="1"
      log "Rollback safety boundary: PASS (persistent scheduler=false delivery=false; runtime closed; Mini App, local auth and observability retained)"
    else
      log "WARNING: rollback could not prove persistent scheduler=false/delivery=false and preserved runtime overlays"
    fi
    log "Rollback never deletes generated snapshots, Telegram outbox rows or named volumes"
  fi
  if [[ -n "$ROLLBACK_ROOT" && -d "$ROLLBACK_ROOT" ]]; then
    if [[ "$SUCCESS" == "1" || "$MUTATED" == "0" || "$ROLLBACK_PROVEN" == "1" ]]; then
      rm -rf "$ROLLBACK_ROOT"
    else
      log "WARNING: rollback backup retained for manual recovery at $ROLLBACK_ROOT"
    fi
  fi
  exit "$rc"
}
trap rollback_on_exit EXIT

log "TG-04 recurring activation start: source=$EXPECTED_SOURCE approved_immediate_deliveries=$EXPECTED_IMMEDIATE"
log "Phase 1: enable scheduler only; Telegram delivery remains disabled"
MUTATED="1"
set_env_values "$CENTRAL_ENV" DAILY_REPORTS_SCHEDULER_ENABLED true
"${COMPOSE[@]}" --env-file "$PIN_ENV" up -d --no-deps --no-build --force-recreate telemetry-service >>"$SUMMARY" 2>&1
wait_healthy "$TELEMETRY_NAME" || { log "ERROR: Telemetry did not become healthy with scheduler enabled"; exit 1; }
[[ "$(image_id "$TELEMETRY_NAME")" == "$OLD_TELEMETRY_IMAGE_ID" ]] || { log "ERROR: Telemetry image changed during activation"; exit 1; }
[[ "$(container_id "$TELEMETRY_NAME")" != "$OLD_TELEMETRY_CONTAINER_ID" ]] || { log "ERROR: Telemetry container was not recreated"; exit 1; }
docker inspect "$TELEMETRY_NAME" --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -Fx 'DAILY_REPORTS_SCHEDULER_ENABLED=true' >/dev/null \
  || { log "ERROR: scheduler flag did not reach Telemetry runtime"; exit 1; }
telemetry_local_auth_ready || { log "ERROR: Telemetry local-auth overlay was not preserved"; exit 1; }
telemetry_observability_ready || { log "ERROR: Telemetry observability overlay was not preserved"; exit 1; }
gateway_disabled_ready || { log "ERROR: Gateway changed before delivery phase"; exit 1; }

PLAN_AFTER_SCHEDULER=""
for _ in $(seq 1 30); do
  if candidate="$($PLAN_SCRIPT --fingerprint-through-id "$OUTBOX_MAX_ID_BEFORE" 2>/dev/null)"; then
    generation="$(printf '%s' "$candidate" | json_field predicted_snapshot_generation_count)"
    snapshots="$(printf '%s' "$candidate" | json_field snapshot_total_count)"
    immediate="$(printf '%s' "$candidate" | json_field predicted_immediate_delivery_count)"
    prefix="$(printf '%s' "$candidate" | json_field prefix_outbox_fingerprint)"
    rows="$(printf '%s' "$candidate" | json_field outbox_rows)"
    if [[ "$generation" == "0" && "$snapshots" == "$((SNAPSHOTS_BEFORE + PLAN_GENERATION))" && "$immediate" == "$EXPECTED_IMMEDIATE" && "$prefix" == "$OUTBOX_FINGERPRINT_BEFORE" && "$rows" == "$OUTBOX_ROWS_BEFORE" ]]; then
      PLAN_AFTER_SCHEDULER="$candidate"; break
    fi
  fi
  sleep 2
done
[[ -n "$PLAN_AFTER_SCHEDULER" ]] || { log "ERROR: scheduler snapshot delta did not converge to the approved plan"; exit 1; }
printf '%s\n' "$PLAN_AFTER_SCHEDULER" >"$PLAN_AFTER_SCHEDULER_FILE"
log "Scheduler reconciliation: PASS (snapshot_delta=$PLAN_GENERATION immediate_delivery_plan=$EXPECTED_IMMEDIATE)"

log "Phase 2: persist topic delivery enablement and start the Gateway worker"
set_env_values "$TELEGRAM_ENV" TELEGRAM_ENABLED true TELEGRAM_MINIAPP_ENABLED true
"${COMPOSE[@]}" --env-file "$PIN_ENV" up -d --no-deps --no-build --force-recreate telegram-gateway >>"$SUMMARY" 2>&1
wait_healthy "$GATEWAY_NAME" || { log "ERROR: Gateway did not become healthy with delivery enabled"; exit 1; }
[[ "$(image_id "$GATEWAY_NAME")" == "$OLD_GATEWAY_IMAGE_ID" ]] || { log "ERROR: Gateway image changed during activation"; exit 1; }
[[ "$(container_id "$GATEWAY_NAME")" != "$OLD_GATEWAY_CONTAINER_ID" ]] || { log "ERROR: Gateway container was not recreated"; exit 1; }
[[ "$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/app/data/telegram-delivery"}}{{.Name}}{{end}}{{end}}' "$GATEWAY_NAME")" == "$OUTBOX_VOLUME" ]] \
  || { log "ERROR: Gateway outbox volume identity changed"; exit 1; }
gateway_enabled_ready || { log "ERROR: enabled Gateway runtime contract failed"; exit 1; }

docker inspect "$GATEWAY_NAME" | python3 -c '
import json,sys
p=json.load(sys.stdin)[0]; env=dict(item.split("=",1) for item in p["Config"]["Env"] if "=" in item)
assert env.get("TELEGRAM_ENABLED")=="true"
assert env.get("TELEGRAM_MINIAPP_ENABLED")=="true"
thread=env.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID","")
assert thread.isdigit() and int(thread)>0
' >/dev/null

PLAN_AFTER_DELIVERY=""
for _ in $(seq 1 60); do
  health="$(curl -fsS --max-time 5 http://127.0.0.1:8090/health/ready 2>/dev/null || true)"
  if candidate="$($PLAN_SCRIPT --fingerprint-through-id "$OUTBOX_MAX_ID_BEFORE" 2>/dev/null)"; then
    rows="$(printf '%s' "$candidate" | json_field outbox_rows)"
    non_sent="$(printf '%s' "$candidate" | json_field outbox_non_sent_rows)"
    dup="$(printf '%s' "$candidate" | json_field outbox_duplicate_risk_rows)"
    topic_sent="$(printf '%s' "$candidate" | json_field outbox_topic_sent_rows)"
    immediate="$(printf '%s' "$candidate" | json_field predicted_immediate_delivery_count)"
    prefix="$(printf '%s' "$candidate" | json_field prefix_outbox_fingerprint)"
    health_ok="$(printf '%s' "$health" | python3 -c 'import json,sys; p=json.load(sys.stdin); print("yes" if p.get("running") is True and p.get("last_poll_at") else "no")' 2>/dev/null || echo no)"
    if [[ "$rows" == "$((OUTBOX_ROWS_BEFORE + EXPECTED_IMMEDIATE))" && "$non_sent" == "0" && "$dup" == "0" && "$topic_sent" == "$((TOPIC_SENT_BEFORE + EXPECTED_IMMEDIATE))" && "$immediate" == "0" && "$prefix" == "$OUTBOX_FINGERPRINT_BEFORE" && "$health_ok" == "yes" ]]; then
      if [[ "$EXPECTED_IMMEDIATE" == "0" ]] || printf '%s' "$health" | python3 -c 'import json,sys; assert json.load(sys.stdin).get("last_send_at")' >/dev/null 2>&1; then
        PLAN_AFTER_DELIVERY="$candidate"; break
      fi
    fi
  fi
  sleep 2
done
[[ -n "$PLAN_AFTER_DELIVERY" ]] || { log "ERROR: Telegram delivery did not converge to the approved exact count"; exit 1; }
printf '%s\n' "$PLAN_AFTER_DELIVERY" >"$PLAN_AFTER_DELIVERY_FILE"

for name in "${CORE_NAMES[@]}"; do
  after="$(container_id "$name")" || { log "ERROR: core container disappeared: $name"; exit 1; }
  [[ "$after" == "${CORE_IDS[$name]}" ]] || { log "ERROR: core container identity changed: $name"; exit 1; }
done
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3000/)" == "200" ]] || { log "ERROR: Dashboard post-check failed"; exit 1; }
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3000/telegram-miniapp)" == "200" ]] || { log "ERROR: Mini App post-check failed"; exit 1; }
[[ "$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/health/ready")" == "200" ]] || { log "ERROR: Telemetry post-check failed"; exit 1; }
SERVE_HASH_AFTER="$(tailscale serve status | sha256sum | awk '{print $1}')"
[[ "$SERVE_HASH_AFTER" == "$SERVE_HASH_BEFORE" ]] || { log "ERROR: Tailscale Serve topology changed"; exit 1; }

python3 - "$CENTRAL_ENV" "$TELEGRAM_ENV" <<'PYFINAL'
from pathlib import Path
import sys

def values(path):
    result={}
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in raw and not raw.lstrip().startswith("#"):
            k,v=raw.split("=",1); result[k.strip()]=v.strip()
    return result
central=values(sys.argv[1]); telegram=values(sys.argv[2])
assert central.get("DAILY_REPORTS_SCHEDULER_ENABLED")=="true"
assert telegram.get("TELEGRAM_ENABLED")=="true"
assert telegram.get("TELEGRAM_MINIAPP_ENABLED")=="true"
thread=telegram.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID","")
assert thread.isdigit() and int(thread)>0
print("Persistent recurring config: PASS (scheduler=true delivery=true miniapp=true topic=present)")
PYFINAL

log "Recurring activation: PASS (scheduler=true delivery=true approved_immediate_deliveries=$EXPECTED_IMMEDIATE)"
log "Historical Telegram rows unchanged: PASS"
log "Outbox volume identity unchanged: PASS"
log "Post-activation outbox has no non-sent or duplicate-risk rows: PASS"
log "Core container identities unchanged: PASS"
log "Dashboard/Telemetry/Mini App healthy and Tailscale Serve unchanged: PASS"
log "No Modbus/hardware write and no named-volume/snapshot/outbox deletion occurred"
log "Evidence: $EVIDENCE_DIR"
SUCCESS="1"
trap - EXIT
rm -rf "$ROLLBACK_ROOT"
exit 0
