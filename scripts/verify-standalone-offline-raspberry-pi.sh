#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
OBSERVATION_SECONDS=60
REQUIRE_LOOPBACK_ONLY=false
ACCESS_TOKEN_FILE=""
ORGANIZATION_ID=""

usage() {
  cat <<'USAGE'
Usage: verify-standalone-offline-raspberry-pi.sh [options]

Options:
  --require-loopback-only       Require no default route and no IPv4 on physical uplinks.
  --observation-seconds N       Telemetry observation window (default: 60, minimum: 5).
  --access-token-file PATH      Optional bearer token file for AUTH_MODE=jwt.
  --organization-id UUID        Organization paired with --access-token-file.
  --help                        Show this help.
USAGE
}

while (($# > 0)); do
  case "$1" in
    --require-loopback-only)
      REQUIRE_LOOPBACK_ONLY=true
      shift
      ;;
    --observation-seconds)
      (($# >= 2)) || { echo "ERROR: --observation-seconds requires a value" >&2; exit 64; }
      OBSERVATION_SECONDS="$2"
      shift 2
      ;;
    --access-token-file)
      (($# >= 2)) || { echo "ERROR: --access-token-file requires a path" >&2; exit 64; }
      ACCESS_TOKEN_FILE="$2"
      shift 2
      ;;
    --organization-id)
      (($# >= 2)) || { echo "ERROR: --organization-id requires a value" >&2; exit 64; }
      ORGANIZATION_ID="$2"
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

[[ "$OBSERVATION_SECONDS" =~ ^[0-9]+$ ]] && ((OBSERVATION_SECONDS >= 5)) \
  || { echo "ERROR: observation seconds must be an integer >= 5" >&2; exit 64; }

for command in git docker curl python3 ip; do
  command -v "$command" >/dev/null 2>&1 || { echo "ERROR: missing command: $command" >&2; exit 1; }
done

docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose v2 is unavailable" >&2; exit 1; }
[[ -d "$REPO/.git" ]] || { echo "ERROR: repository not found: $REPO" >&2; exit 1; }

CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
EDGE_ENV="$CENTRAL_DIR/.env.edge-central"
MODE_FILE="$REPO/runtime/runtime-mode"
[[ -r "$CENTRAL_ENV" ]] || { echo "ERROR: missing $CENTRAL_ENV" >&2; exit 1; }
[[ -r "$EDGE_ENV" ]] || { echo "ERROR: missing $EDGE_ENV" >&2; exit 1; }
[[ -r "$MODE_FILE" ]] || { echo "ERROR: deployment runtime-mode evidence is missing" >&2; exit 1; }

RUNTIME_MODE="$(tr -d '\r\n' < "$MODE_FILE")"
[[ "$RUNTIME_MODE" == "standalone" ]] \
  || { echo "ERROR: active runtime mode is '$RUNTIME_MODE', expected standalone" >&2; exit 1; }

AUTH_MODE="$(awk -F= '$1=="AUTH_MODE" {sub(/^[^=]*=/, ""); print; exit}' "$CENTRAL_ENV")"
[[ -n "$AUTH_MODE" ]] || { echo "ERROR: AUTH_MODE is not configured" >&2; exit 1; }

TOKEN=""
CURL_CONFIG=""
cleanup() {
  if [[ -n "$CURL_CONFIG" && -f "$CURL_CONFIG" ]]; then
    rm -f "$CURL_CONFIG"
  fi
  unset TOKEN
}
trap cleanup EXIT

if [[ "$AUTH_MODE" == "jwt" ]]; then
  [[ -r "$ACCESS_TOKEN_FILE" ]] || { echo "ERROR: AUTH_MODE=jwt requires --access-token-file" >&2; exit 1; }
  [[ -n "$ORGANIZATION_ID" ]] || { echo "ERROR: AUTH_MODE=jwt requires --organization-id" >&2; exit 1; }
  TOKEN="$(tr -d '\r\n' < "$ACCESS_TOKEN_FILE")"
  [[ -n "$TOKEN" ]] || { echo "ERROR: access token file is empty" >&2; exit 1; }
  CURL_CONFIG="$(mktemp)"
  chmod 0600 "$CURL_CONFIG"
  {
    printf 'header = "Authorization: Bearer %s"\n' "$TOKEN"
    printf 'header = "X-Organization-ID: %s"\n' "$ORGANIZATION_ID"
  } > "$CURL_CONFIG"
elif [[ -n "$ACCESS_TOKEN_FILE" || -n "$ORGANIZATION_ID" ]]; then
  echo "ERROR: token options are only valid for AUTH_MODE=jwt" >&2
  exit 64
fi

api_get() {
  local url=$1
  if [[ -n "$CURL_CONFIG" ]]; then
    curl --config "$CURL_CONFIG" -fsS --max-time 15 "$url"
  else
    curl -fsS --max-time 15 "$url"
  fi
}

container_id() {
  local project=$1 service=$2
  docker ps -aq \
    --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service" \
    | head -n 1
}

require_running_container() {
  local project=$1 service=$2
  local id status health
  id="$(container_id "$project" "$service")"
  [[ -n "$id" ]] || { echo "ERROR: missing container $project/$service" >&2; return 1; }
  status="$(docker inspect -f '{{.State.Status}}' "$id")"
  [[ "$status" == "running" ]] || { echo "ERROR: $project/$service is $status" >&2; return 1; }
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$id")"
  [[ "$health" == "healthy" || "$health" == "none" ]] \
    || { echo "ERROR: $project/$service health is $health" >&2; return 1; }
  printf '%s\n' "$id"
}

require_completed_container() {
  local project=$1 service=$2
  local id status exit_code
  id="$(container_id "$project" "$service")"
  [[ -n "$id" ]] || { echo "ERROR: missing container $project/$service" >&2; return 1; }
  status="$(docker inspect -f '{{.State.Status}}' "$id")"
  exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$id")"
  [[ "$status" == "exited" && "$exit_code" == "0" ]] \
    || { echo "ERROR: $project/$service status=$status exit=$exit_code" >&2; return 1; }
  printf '%s\n' "$id"
}

if [[ "$REQUIRE_LOOPBACK_ONLY" == "true" ]]; then
  if ip route show default | grep -q .; then
    echo "ERROR: a default route is still present" >&2
    exit 1
  fi
  PHYSICAL_IPV4="$(ip -4 -o addr show up scope global \
    | awk '$2 ~ /^(eth|en|wlan|wl|wwan)/ {print $2 "=" $4}')"
  [[ -z "$PHYSICAL_IPV4" ]] \
    || { echo "ERROR: physical uplink IPv4 is still active: $PHYSICAL_IPV4" >&2; exit 1; }
fi

CENTRAL_MQTT_ID="$(require_running_container nexolab-central mqtt)"
POSTGRES_ID="$(require_running_container nexolab-central postgres)"
MINIO_ID="$(require_running_container nexolab-central minio)"
TELEMETRY_ID="$(require_running_container nexolab-central telemetry-service)"
EDGE_MQTT_ID="$(require_running_container nexolab-edge mqtt)"
DEVICE_AGENT_ID="$(require_running_container nexolab-edge device-agent)"
MIGRATE_ID="$(require_completed_container nexolab-central telemetry-migrate)"

curl -fsS --max-time 15 http://127.0.0.1:3000 >/dev/null
api_get http://127.0.0.1:8082/health/ready \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("status")=="ready"; assert p.get("database")=="ready"; assert p.get("mqtt")=="ready"'
api_get http://127.0.0.1:8082/api/v1/auth/session \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("authenticated") is True; assert isinstance(p.get("identity"),dict); assert p.get("memberships")'
curl -fsS --max-time 15 http://127.0.0.1:8081/health \
  | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p.get("status") in {"ok","ready","healthy"}'

docker exec "$TELEMETRY_ID" alembic current --check-heads >/dev/null
docker exec "$CENTRAL_MQTT_ID" sh -ec \
  "mosquitto_sub -h 127.0.0.1 -t '\$SYS/broker/version' -C 1 -W 5 >/dev/null"

if [[ "$AUTH_MODE" == "jwt" ]]; then
  docker exec -i \
    -e NEXOLAB_VERIFY_ACCESS_TOKEN="$TOKEN" \
    -e NEXOLAB_VERIFY_ORGANIZATION_ID="$ORGANIZATION_ID" \
    "$TELEMETRY_ID" python - <<'PY'
import asyncio
import json
import os
import websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:8082/api/v1/telemetry/live",
        open_timeout=8,
        close_timeout=5,
    ) as socket:
        await socket.send(json.dumps({
            "type": "authenticate",
            "access_token": os.environ["NEXOLAB_VERIFY_ACCESS_TOKEN"],
            "organization_id": os.environ["NEXOLAB_VERIFY_ORGANIZATION_ID"],
        }))
        payload = json.loads(await asyncio.wait_for(socket.recv(), timeout=8))
        if payload.get("type") != "authenticated":
            raise SystemExit(f"unexpected websocket authentication response: {payload.get('type')}")

asyncio.run(main())
PY
else
  docker exec -i "$TELEMETRY_ID" python - <<'PY'
import asyncio
import json
import websockets

async def main():
    async with websockets.connect(
        "ws://127.0.0.1:8082/api/v1/telemetry/live",
        open_timeout=8,
        close_timeout=5,
    ) as socket:
        payload = json.loads(await asyncio.wait_for(socket.recv(), timeout=30))
        if not isinstance(payload, dict):
            raise SystemExit("websocket payload is not an object")

asyncio.run(main())
PY
fi

latest_captured_at() {
  api_get 'http://127.0.0.1:8082/api/v1/telemetry/latest?limit=100' \
    | python3 -c '
import json, sys
payload = json.load(sys.stdin)
items = payload.get("items", []) if isinstance(payload, dict) else payload
if not isinstance(items, list):
    raise SystemExit("latest telemetry response has no items list")
values = [item.get("captured_at") for item in items if isinstance(item, dict) and item.get("captured_at")]
if not values:
    raise SystemExit("no telemetry samples are available")
print(max(values))
'
}

CAPTURED_BEFORE="$(latest_captured_at)"
sleep "$OBSERVATION_SECONDS"
CAPTURED_AFTER="$(latest_captured_at)"
python3 - "$CAPTURED_BEFORE" "$CAPTURED_AFTER" <<'PY'
from datetime import datetime
import sys

before = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
after = datetime.fromisoformat(sys.argv[2].replace("Z", "+00:00"))
if after <= before:
    raise SystemExit(f"telemetry did not advance: before={before.isoformat()} after={after.isoformat()}")
PY

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/evidence/standalone-offline-$STAMP"
mkdir -p "$EVIDENCE_DIR"
chmod 0700 "$EVIDENCE_DIR"
{
  echo "verified_at=$(date --iso-8601=seconds)"
  echo "commit=$(git -C "$REPO" rev-parse HEAD)"
  echo "runtime_mode=$RUNTIME_MODE"
  echo "auth_mode=$AUTH_MODE"
  echo "require_loopback_only=$REQUIRE_LOOPBACK_ONLY"
  echo "observation_seconds=$OBSERVATION_SECONDS"
  echo "captured_before=$CAPTURED_BEFORE"
  echo "captured_after=$CAPTURED_AFTER"
  echo "dashboard=http://127.0.0.1:3000"
  echo "api=http://127.0.0.1:8082"
  echo "websocket=ws://127.0.0.1:8082/api/v1/telemetry/live"
  echo "central_mqtt_container=$CENTRAL_MQTT_ID"
  echo "postgres_container=$POSTGRES_ID"
  echo "minio_container=$MINIO_ID"
  echo "telemetry_container=$TELEMETRY_ID"
  echo "edge_mqtt_container=$EDGE_MQTT_ID"
  echo "device_agent_container=$DEVICE_AGENT_ID"
  echo "migration_container=$MIGRATE_ID"
  echo "result=passed"
} > "$EVIDENCE_DIR/summary.txt"
chmod 0600 "$EVIDENCE_DIR/summary.txt"

printf 'STANDALONE OFFLINE VERIFICATION PASSED\n'
printf 'Evidence: %s\n' "$EVIDENCE_DIR"
