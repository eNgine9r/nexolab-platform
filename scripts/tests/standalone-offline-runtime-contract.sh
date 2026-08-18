#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../lib/raspberry-pi-runtime-mode.sh
source "$REPO_ROOT/scripts/lib/raspberry-pi-runtime-mode.sh"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

assert_eq() {
  local expected=$1 actual=$2 label=$3
  [[ "$actual" == "$expected" ]] || fail "$label: expected '$expected', got '$actual'"
}

bash -n "$REPO_ROOT/scripts/deploy-current-head-raspberry-pi.sh"
bash -n "$REPO_ROOT/scripts/verify-standalone-offline-raspberry-pi.sh"
bash -n "$REPO_ROOT/scripts/lib/raspberry-pi-runtime-mode.sh"
python3 "$REPO_ROOT/scripts/tests/test_deploy_current_head_raspberry_pi_auth.py"

nexolab_configure_runtime_contract standalone ""
assert_eq standalone "$NEXOLAB_RUNTIME_MODE" "standalone mode"
assert_eq 127.0.0.1 "$NEXOLAB_HOST_BIND_ADDRESS" "standalone host bind"
assert_eq 127.0.0.1 "$NEXOLAB_DASHBOARD_BIND_ADDRESS" "standalone dashboard bind"
assert_eq http://127.0.0.1:3000 "$NEXOLAB_DASHBOARD_ORIGIN" "standalone dashboard origin"
assert_eq http://127.0.0.1:8082 "$NEXOLAB_API_BASE_URL" "standalone API"
assert_eq ws://127.0.0.1:8082/api/v1/telemetry/live "$NEXOLAB_WEBSOCKET_URL" "standalone WebSocket"
assert_eq http://127.0.0.1:3000,http://localhost:3000 "$NEXOLAB_CORS_ALLOWED_ORIGINS" "standalone CORS"
assert_eq central-mqtt "$NEXOLAB_EDGE_CENTRAL_MQTT_HOST" "standalone central MQTT DNS"
assert_eq 1883 "$NEXOLAB_EDGE_CENTRAL_MQTT_PORT" "standalone central MQTT port"
assert_eq docker.service "$NEXOLAB_SYSTEMD_AFTER" "standalone systemd after"
assert_eq "" "$NEXOLAB_SYSTEMD_WANTS" "standalone systemd wants"

nexolab_configure_runtime_contract lan 192.0.2.15
assert_eq lan "$NEXOLAB_RUNTIME_MODE" "lan mode"
assert_eq 192.0.2.15 "$NEXOLAB_HOST_BIND_ADDRESS" "lan host bind"
assert_eq 0.0.0.0 "$NEXOLAB_DASHBOARD_BIND_ADDRESS" "lan dashboard bind"
assert_eq http://192.0.2.15:3000 "$NEXOLAB_DASHBOARD_ORIGIN" "lan dashboard origin"
assert_eq 192.0.2.15 "$NEXOLAB_EDGE_CENTRAL_MQTT_HOST" "lan central MQTT host"
assert_eq 1884 "$NEXOLAB_EDGE_CENTRAL_MQTT_PORT" "lan central MQTT port"
assert_eq "network-online.target docker.service" "$NEXOLAB_SYSTEMD_AFTER" "lan systemd after"
assert_eq network-online.target "$NEXOLAB_SYSTEMD_WANTS" "lan systemd wants"

if nexolab_configure_runtime_contract invalid "" >/dev/null 2>&1; then
  fail "invalid runtime mode was accepted"
fi
if nexolab_configure_runtime_contract lan 127.0.0.1 >/dev/null 2>&1; then
  fail "lan mode accepted loopback as trusted bind"
fi

TEMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEMP_ROOT"' EXIT
set +e
NEXOLAB_REPO="$TEMP_ROOT/repo" \
  bash "$REPO_ROOT/scripts/deploy-current-head-raspberry-pi.sh" --runtime-mode invalid \
  >"$TEMP_ROOT/invalid.out" 2>&1
INVALID_RC=$?
set -e
assert_eq 64 "$INVALID_RC" "invalid mode exit code"
[[ ! -e "$TEMP_ROOT/repo/runtime" ]] || fail "invalid mode mutated the runtime directory"

CENTRAL_ENV="$TEMP_ROOT/central.env"
EDGE_ENV="$TEMP_ROOT/edge.env"
cat > "$CENTRAL_ENV" <<'ENV'
CENTRAL_RESOURCE_PREFIX=nexolab-central
CENTRAL_BIND_ADDRESS=127.0.0.1
CENTRAL_API_PORT=8082
CENTRAL_MQTT_PORT=1884
CENTRAL_OBJECT_STORAGE_PORT=9000
CENTRAL_OBJECT_STORAGE_CONSOLE_PORT=9001
STANDALONE_RUNTIME_NETWORK=nexolab-standalone-runtime
POSTGRES_DB=nexolab
POSTGRES_USER=nexolab
POSTGRES_PASSWORD=test_database_password
MINIO_ROOT_USER=nexolab-storage
MINIO_ROOT_PASSWORD=test_storage_password
OBJECT_STORAGE_BUCKET=nexolab-equipment-images
CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
CORS_ALLOW_CREDENTIALS=false
AUTH_MODE=disabled
AUTH_DEFAULT_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001
MQTT_TOPIC=nexolab/telemetry
MQTT_CLIENT_ID=nexolab-central-telemetry-ingestion
GRAFANA_ADMIN_PASSWORD=test_grafana_password
OBSERVABILITY_BIND_ADDRESS=127.0.0.1
ENV

cat > "$EDGE_ENV" <<'ENV'
NEXOLAB_NODE_ID=edge-01
DEVICE_AGENT_IMAGE=nexolab-device-agent:local
RS485_HOST_DEVICE=/dev/serial/by-id/usb-NEXOLAB-test-if00-port0
RS485_GROUP_GID=20
STANDALONE_RUNTIME_NETWORK=nexolab-standalone-runtime
CENTRAL_MQTT_HOST=central-mqtt
CENTRAL_MQTT_PORT=1883
CENTRAL_MQTT_TOPIC=nexolab/telemetry
ENV

command -v docker >/dev/null 2>&1 || fail "docker is required for Compose contract validation"
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"

docker compose --env-file "$CENTRAL_ENV" \
  -f "$REPO_ROOT/infrastructure/compose/compose.central.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.observability.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.central-standalone.yaml" \
  config --quiet
docker compose --env-file "$EDGE_ENV" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.hardware.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge-central-bridge.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge-standalone.yaml" \
  config --quiet

CENTRAL_JSON="$TEMP_ROOT/central.json"
EDGE_JSON="$TEMP_ROOT/edge.json"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$REPO_ROOT/infrastructure/compose/compose.central.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.central-standalone.yaml" \
  config --format json > "$CENTRAL_JSON"
docker compose --env-file "$EDGE_ENV" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.hardware.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge-central-bridge.yaml" \
  -f "$REPO_ROOT/infrastructure/compose/compose.edge-standalone.yaml" \
  config --format json > "$EDGE_JSON"

python3 - "$CENTRAL_JSON" "$EDGE_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    central = json.load(handle)
with open(sys.argv[2], encoding="utf-8") as handle:
    edge = json.load(handle)

central_services = central["services"]
edge_services = edge["services"]

assert set(central_services["telemetry-service"]["networks"]) == {"central"}
assert set(central_services["mqtt"]["networks"]) == {"central", "standalone-runtime"}
assert central_services["mqtt"]["networks"]["standalone-runtime"]["aliases"] == ["central-mqtt"]
assert central["networks"]["standalone-runtime"]["name"] == "nexolab-standalone-runtime"

assert set(edge_services["mqtt"]["networks"]) == {"default", "standalone-runtime"}
assert set(edge_services["device-agent"]["networks"]) == {"default"}
assert edge["networks"]["standalone-runtime"]["external"] is True
assert edge["networks"]["standalone-runtime"]["name"] == "nexolab-standalone-runtime"
assert edge_services["mqtt"]["environment"]["CENTRAL_MQTT_HOST"] == "central-mqtt"
assert str(edge_services["mqtt"]["environment"]["CENTRAL_MQTT_PORT"]) == "1883"

device_agent = edge_services["device-agent"]
assert device_agent["environment"]["SERIAL_DEVICE"] == (
    "/host/dev/serial/by-id/usb-NEXOLAB-test-if00-port0"
)
assert device_agent.get("privileged") in (None, False)
assert device_agent.get("devices") in (None, [])
assert device_agent["device_cgroup_rules"] == ["c 188:* rwm"]

host_dev_mounts = [
    volume
    for volume in device_agent["volumes"]
    if volume.get("target") == "/host/dev"
]
assert len(host_dev_mounts) == 1
host_dev_mount = host_dev_mounts[0]
assert host_dev_mount["type"] == "bind"
assert host_dev_mount["source"] == "/dev"
assert host_dev_mount["read_only"] is True
PY

printf 'Standalone offline runtime contract checks passed.\n'
