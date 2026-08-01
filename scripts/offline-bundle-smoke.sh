#!/usr/bin/env bash
set -Eeuo pipefail

CENTRAL_ENV=""
EDGE_ENV=""
SKIP_EDGE=false
while (($#)); do
  case "$1" in
    --central-env) CENTRAL_ENV="${2:?}"; shift 2 ;;
    --edge-env) EDGE_ENV="${2:?}"; shift 2 ;;
    --skip-edge) SKIP_EDGE=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -f "$CENTRAL_ENV" ]] || { echo "Missing --central-env" >&2; exit 2; }
if [[ "$SKIP_EDGE" == false ]]; then
  [[ -f "$EDGE_ENV" ]] || { echo "Missing --edge-env" >&2; exit 2; }
fi
for command in docker curl python3; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CENTRAL_BASE="$BUNDLE_ROOT/deploy/compose/compose.central.yaml"
CENTRAL_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.central.offline.yaml"
EDGE_BASE="$BUNDLE_ROOT/deploy/compose/compose.edge.yaml"
EDGE_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.edge.offline.yaml"

env_value() {
  local file="$1" key="$2" default="$3" value
  value="$(sed -n "s/^${key}=//p" "$file" | tail -n 1)"
  printf '%s' "${value:-$default}"
}

CENTRAL_BIND="$(env_value "$CENTRAL_ENV" CENTRAL_BIND_ADDRESS 127.0.0.1)"
CENTRAL_API_PORT="$(env_value "$CENTRAL_ENV" CENTRAL_API_PORT 8082)"
OBJECT_PORT="$(env_value "$CENTRAL_ENV" CENTRAL_OBJECT_STORAGE_PORT 9000)"
DASHBOARD_BIND="$(env_value "$CENTRAL_ENV" DASHBOARD_BIND_ADDRESS 127.0.0.1)"
DASHBOARD_PORT="$(env_value "$CENTRAL_ENV" DASHBOARD_PORT 3000)"

CENTRAL=(docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_BASE" -f "$CENTRAL_OFFLINE")
"${CENTRAL[@]}" ps --format json > /tmp/nexolab-offline-central-ps.json
curl --fail --silent --show-error "http://${CENTRAL_BIND}:${CENTRAL_API_PORT}/health/ready" >/tmp/nexolab-offline-ready.json
curl --fail --silent --show-error "http://${DASHBOARD_BIND}:${DASHBOARD_PORT}/" >/dev/null
curl --fail --silent --show-error "http://${CENTRAL_BIND}:${OBJECT_PORT}/minio/health/live" >/dev/null
"${CENTRAL[@]}" exec -T postgres sh -ec 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
"${CENTRAL[@]}" exec -T mqtt sh -ec "mosquitto_sub -h 127.0.0.1 -t '\$SYS/broker/version' -C 1 -W 5 >/dev/null"

"${CENTRAL[@]}" exec -T dashboard node - <<'NODE'
const socket = new WebSocket("ws://telemetry-service:8082/api/v1/telemetry/live");
const timeout = setTimeout(() => {
  console.error("WebSocket smoke timed out before application-level evidence");
  socket.close(4000, "smoke timeout");
  process.exit(1);
}, 30000);
socket.addEventListener("message", (event) => {
  try {
    const payload = JSON.parse(String(event.data));
    if (["heartbeat", "sample", "authenticated"].includes(payload.type)) {
      clearTimeout(timeout);
      socket.close(1000, "offline smoke complete");
      process.exit(0);
    }
  } catch (error) {
    console.error(error);
    process.exit(1);
  }
});
socket.addEventListener("error", () => {
  console.error("WebSocket smoke transport error");
  process.exit(1);
});
NODE

if [[ "$SKIP_EDGE" == false ]]; then
  EDGE=(docker compose --env-file "$EDGE_ENV" -f "$EDGE_BASE" -f "$EDGE_OFFLINE")
  "${EDGE[@]}" ps --format json > /tmp/nexolab-offline-edge-ps.json
  curl --fail --silent --show-error http://127.0.0.1:8081/health >/tmp/nexolab-offline-edge-health.json
fi

python3 - /tmp/nexolab-offline-ready.json <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "ready":
    raise SystemExit(f"Central readiness is not ready: {payload}")
PY

echo "Offline smoke passed: dashboard, API, WebSocket, MQTT, PostgreSQL, MinIO${SKIP_EDGE:+ and edge simulator}."
