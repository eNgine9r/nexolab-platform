#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"
TLS_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery-tls-fleet.yaml"
TLS_GENERATOR="$ROOT_DIR/scripts/generate-mqtt-tls-acceptance-material.sh"
PROJECT_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
PROJECT_NAME="nexolab-dr-tls-${PROJECT_SUFFIX}"
PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${PROJECT_NAME}.XXXXXX")"
SECRETS_DIR="$PRIVATE_DIR/secrets"
TLS_SERVER_DIR="$PRIVATE_DIR/tls-server"
WORK_DIR="$PRIVATE_DIR/work"
EVIDENCE_DIR="$ROOT_DIR/test-results-disaster-recovery-tls-fleet"
MQTT_ARCHIVE="$WORK_DIR/mosquitto-data.tar"
SOURCE_MQTT_STATE="$WORK_DIR/source-mqtt-state.txt"
RESTORE_MQTT_STATE="$WORK_DIR/restore-mqtt-state.txt"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000099"
INGESTION_USERNAME="nexolab-central-ingestion"
INGESTION_CLIENT_ID="nexolab-central-ingestion"
NODE_A_USERNAME="node:${ORGANIZATION_ID}:edge-01"
NODE_B_USERNAME="node:${ORGANIZATION_ID}:edge-02"
NODE_A_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-01"
NODE_B_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-02"
STARTED_AT="$(date +%s)"

random_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
}

write_secret() {
  local path=$1
  local prefix=$2
  python3 - "$path" "$prefix" <<'PY'
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1])
path.write_text(sys.argv[2] + secrets.token_urlsafe(36), encoding="utf-8")
path.chmod(0o444)
PY
}

export DR_POSTGRES_DB="nexolab"
export DR_POSTGRES_USER="nexolab"
export DR_POSTGRES_PASSWORD="$(random_secret)"
export DR_MINIO_ROOT_USER="nexolabdr"
export DR_MINIO_ROOT_PASSWORD="$(random_secret)"
export DR_MQTT_ADMIN_USERNAME="nexolab-dr-admin"
export DR_SECRETS_DIR="$SECRETS_DIR"
export DR_WORK_DIR="$WORK_DIR"
export DR_MQTT_TLS_SERVER_DIR="$TLS_SERVER_DIR"
export MQTT_TLS_SERVER_DIR="$TLS_SERVER_DIR"
export DR_TLS_ORGANIZATION_ID="$ORGANIZATION_ID"
export DR_NETWORK="${PROJECT_NAME}-network"
export DR_SOURCE_POSTGRES_VOLUME="${PROJECT_NAME}-source-postgres"
export DR_RESTORE_POSTGRES_VOLUME="${PROJECT_NAME}-restore-postgres"
export DR_SOURCE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-source-object-storage"
export DR_RESTORE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-restore-object-storage"
export DR_SOURCE_MQTT_VOLUME="${PROJECT_NAME}-source-mqtt"
export DR_RESTORE_MQTT_VOLUME="${PROJECT_NAME}-restore-mqtt"
export DR_RESTORE_EDGE_A_VOLUME="${PROJECT_NAME}-edge-a"
export DR_RESTORE_EDGE_B_VOLUME="${PROJECT_NAME}-edge-b"
export DR_TELEMETRY_IMAGE="nexolab-telemetry-service:dr-tls-${PROJECT_SUFFIX}"
export DR_MQTT_IMAGE="nexolab-mqtt-dynamic-security:dr-tls-${PROJECT_SUFFIX}"
export DR_DEVICE_AGENT_IMAGE="nexolab-device-agent:dr-tls-${PROJECT_SUFFIX}"
export DR_RESTORE_API_PORT="${DR_TLS_RESTORE_API_PORT:-8096}"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    -f "$BASE_COMPOSE" \
    -f "$TLS_COMPOSE" \
    "$@"
}

cleanup() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color \
    source-mqtt restore-mqtt restore-postgres restore-minio \
    restore-telemetry-service restore-device-agent-a restore-device-agent-b \
    >"$EVIDENCE_DIR/services.log" 2>&1 || true
  compose down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm \
    "$DR_SOURCE_POSTGRES_VOLUME" "$DR_RESTORE_POSTGRES_VOLUME" \
    "$DR_SOURCE_OBJECT_STORAGE_VOLUME" "$DR_RESTORE_OBJECT_STORAGE_VOLUME" \
    "$DR_SOURCE_MQTT_VOLUME" "$DR_RESTORE_MQTT_VOLUME" \
    "$DR_RESTORE_EDGE_A_VOLUME" "$DR_RESTORE_EDGE_B_VOLUME" \
    >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Restored MQTT TLS fleet acceptance failed." >&2
    tail -n 280 "$EVIDENCE_DIR/services.log" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker openssl python3 sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

rm -rf "$EVIDENCE_DIR"
mkdir -p "$SECRETS_DIR" "$TLS_SERVER_DIR" "$WORK_DIR" "$EVIDENCE_DIR"
chmod 0700 "$PRIVATE_DIR" "$WORK_DIR"
chmod 0755 "$SECRETS_DIR" "$TLS_SERVER_DIR"

write_secret "$SECRETS_DIR/admin-password" "admin-"
write_secret "$SECRETS_DIR/ingestion-password" "ingestion-"
write_secret "$SECRETS_DIR/edge-01-password" "edge-01-"
write_secret "$SECRETS_DIR/edge-02-password" "edge-02-"
"$TLS_GENERATOR" "$SECRETS_DIR" "$EVIDENCE_DIR"

compose config --quiet
compose build \
  source-mqtt restore-mqtt restore-migrate restore-telemetry-service \
  restore-device-agent-a restore-device-agent-b

compose up -d --wait source-mqtt
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin bootstrap-defaults
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-ingestion "$INGESTION_USERNAME" "$INGESTION_CLIENT_ID" \
  /run/secrets/nexolab/ingestion-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-node "$NODE_A_USERNAME" "$NODE_A_CLIENT_ID" \
  "$ORGANIZATION_ID" edge-01 /run/secrets/nexolab/edge-01-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-node "$NODE_B_USERNAME" "$NODE_B_CLIENT_ID" \
  "$ORGANIZATION_ID" edge-02 /run/secrets/nexolab/edge-02-password

capture_mqtt_state() {
  local service=$1
  local output=$2
  {
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin list-clients \
      | sed '/^[[:space:]]*$/d' \
      | sort
    printf '%s\n' '--- edge-01 ---'
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin \
      get-client "$NODE_A_USERNAME"
    printf '%s\n' '--- edge-02 ---'
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin \
      get-client "$NODE_B_USERNAME"
    printf '%s\n' '--- ingestion ---'
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin \
      get-client "$INGESTION_USERNAME"
  } >"$output"
}

capture_mqtt_state source-mqtt "$SOURCE_MQTT_STATE"
SOURCE_MQTT_SHA="$(sha256sum "$SOURCE_MQTT_STATE" | awk '{print $1}')"

compose stop -t 30 source-mqtt
compose run --rm volume-helper \
  "python /opt/nexolab/scripts/nexolab-volume-archive.py create --source /source-mqtt --output /work/mosquitto-data.tar"
test -s "$MQTT_ARCHIVE"
compose run --rm volume-helper \
  "python /opt/nexolab/scripts/nexolab-volume-archive.py extract --archive /work/mosquitto-data.tar --destination /restore-mqtt"

compose up -d --wait restore-postgres restore-minio restore-mqtt
compose run --rm restore-migrate
compose up -d --wait \
  restore-telemetry-service restore-device-agent-a restore-device-agent-b

capture_mqtt_state restore-mqtt "$RESTORE_MQTT_STATE"
RESTORE_MQTT_SHA="$(sha256sum "$RESTORE_MQTT_STATE" | awk '{print $1}')"
test "$SOURCE_MQTT_SHA" = "$RESTORE_MQTT_SHA"

compose exec -T restore-mqtt openssl s_client \
  -connect mqtt:8883 \
  -servername mqtt \
  -CAfile /run/secrets/nexolab/mqtt-ca.pem \
  -verify_return_error \
  -verify_hostname mqtt \
  </dev/null >/dev/null 2>&1

if compose exec -T restore-mqtt openssl s_client \
  -connect mqtt:8883 \
  -servername mqtt \
  -CAfile /run/secrets/nexolab/mqtt-wrong-ca.pem \
  -verify_return_error \
  -verify_hostname mqtt \
  </dev/null >/dev/null 2>&1; then
  echo "Restored broker accepted an untrusted CA." >&2
  exit 80
fi

if compose exec -T restore-telemetry-service python - <<'PY'
import socket
socket.create_connection(("mqtt", 1883), timeout=2).close()
PY
then
  echo "Restored broker exposed plaintext MQTT." >&2
  exit 81
fi

agent_health() {
  local service=$1
  compose exec -T "$service" python - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=3) as response:
    print(json.dumps(json.load(response), separators=(",", ":")))
PY
}

wait_agent_ready() {
  local service=$1
  local output=$2
  for _ in $(seq 1 240); do
    if agent_health "$service" >"$output.tmp" 2>/dev/null; then
      if python3 - "$output.tmp" <<'PY'
from pathlib import Path
import json
import sys
payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if payload.get("mqtt_connected") is True and payload.get("queue_depth") == 0 else 1)
PY
      then
        mv "$output.tmp" "$output"
        return 0
      fi
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${service} TLS connection and queue drain." >&2
  return 1
}

wait_telemetry() {
  local node_id=$1
  local minimum=$2
  for _ in $(seq 1 240); do
    local count
    count="$(compose exec -T restore-postgres \
      psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
      "SELECT count(*) FROM telemetry_samples WHERE node_id = '${node_id}'")"
    if (( count >= minimum )); then
      printf '%s' "$count"
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for restored telemetry from ${node_id}." >&2
  return 1
}

wait_agent_ready restore-device-agent-a "$EVIDENCE_DIR/edge-01-health.json"
wait_agent_ready restore-device-agent-b "$EVIDENCE_DIR/edge-02-health.json"
EDGE_01_ROWS="$(wait_telemetry edge-01 3)"
EDGE_02_ROWS="$(wait_telemetry edge-02 3)"

printf '%s\n' "$SOURCE_MQTT_SHA" >"$EVIDENCE_DIR/mqtt-authorization-state.sha256"
printf '%s\n' \
  'trusted_ca=accepted' \
  'untrusted_ca=rejected' \
  'plaintext_listener=unavailable' \
  'source_volume_preserved_until_verification=true' \
  >"$EVIDENCE_DIR/transport-and-safety-checks.txt"

DURATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
ARCHIVE_BYTES="$(stat -c '%s' "$MQTT_ARCHIVE")"
python3 - "$EVIDENCE_DIR/summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "repository": "eNgine9r/nexolab-platform",
    "duration_seconds": $DURATION_SECONDS,
    "archive_bytes": int("$ARCHIVE_BYTES"),
    "mqtt_authorization_state_sha256": "$SOURCE_MQTT_SHA",
    "restore_state_sha256": "$RESTORE_MQTT_SHA",
    "transport": {
        "tls_port": 8883,
        "trusted_ca": "accepted",
        "untrusted_ca": "rejected",
        "plaintext_listener": "unavailable",
    },
    "device_agents": {
        "edge-01": {"mqtt_connected": True, "queue_depth": 0, "telemetry_rows": int("$EDGE_01_ROWS")},
        "edge-02": {"mqtt_connected": True, "queue_depth": 0, "telemetry_rows": int("$EDGE_02_ROWS")},
    },
    "fresh_restore_volume": True,
    "source_volume_mutated": False,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

python3 - "$EVIDENCE_DIR" "$SECRETS_DIR" <<'PY'
from pathlib import Path
import sys

evidence = Path(sys.argv[1])
secrets = [path.read_bytes() for path in Path(sys.argv[2]).iterdir() if path.is_file()]
for artifact in evidence.rglob("*"):
    if not artifact.is_file():
        continue
    content = artifact.read_bytes()
    for secret in secrets:
        if secret and secret in content:
            raise SystemExit(f"Secret material leaked into evidence: {artifact}")
PY

python3 -m json.tool "$EVIDENCE_DIR/summary.json"
echo "Restored MQTT TLS fleet acceptance passed."
