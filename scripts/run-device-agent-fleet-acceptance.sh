#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.broker-control-acceptance.yaml"
FLEET_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.device-agent-fleet-acceptance.yaml"
EXTRA_COMPOSE="${FLEET_EXTRA_COMPOSE_FILE:-}"
SETUP_HOOK="${FLEET_SETUP_HOOK:-}"
PROJECT_NAME="${FLEET_PROJECT_NAME:-nexolab-device-agent-fleet-acceptance}"
EVIDENCE_DIR="${FLEET_EVIDENCE_DIR:-$ROOT_DIR/test-results-device-agent-fleet}"
PRIVATE_DIR="${TMPDIR:-/tmp}/${PROJECT_NAME}-private"
SECRETS_DIR="$PRIVATE_DIR/secrets"
SERVICE_LOG="$EVIDENCE_DIR/services.log"
FRONTEND_LOG="$EVIDENCE_DIR/frontend.log"
FRONTEND_PID=""
FRONTEND_PORT="${FLEET_FRONTEND_PORT:-3112}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"

API_PORT="${FLEET_API_PORT:-8092}"
MQTT_PORT="${FLEET_MQTT_PORT:-1892}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
POSTGRES_DB="nexolab"
POSTGRES_USER="nexolab"
POSTGRES_PASSWORD="fleet-acceptance-postgres-secret"
ADMIN_USERNAME="nexolab-security-admin"
INGESTION_USERNAME="nexolab-central-ingestion"
INGESTION_CLIENT_ID="nexolab-central-ingestion"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000001"
MANAGER_ID="42000000-0000-0000-0000-000000000011"
MANAGER_MEMBERSHIP="52000000-0000-0000-0000-000000000011"
MANAGER_SUBJECT="manager-device-agent-fleet-acceptance"
JWT_SECRET="device-agent-fleet-acceptance-secret-with-at-least-thirty-two-bytes"
JWT_ISSUER="https://auth.nexolab.local/device-agent-fleet-acceptance"
JWT_AUDIENCE="nexolab-device-agent-fleet-acceptance"
NODE_A="edge-01"
NODE_B="edge-02"

export POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export NEXOLAB_MQTT_ADMIN_USERNAME="$ADMIN_USERNAME"
export BROKER_CONTROL_INGESTION_USERNAME="$INGESTION_USERNAME"
export BROKER_CONTROL_INGESTION_CLIENT_ID="$INGESTION_CLIENT_ID"
export BROKER_CONTROL_ORGANIZATION_A="$ORGANIZATION_ID"
export BROKER_CONTROL_JWT_SECRET="$JWT_SECRET"
export BROKER_CONTROL_JWT_ISSUER="$JWT_ISSUER"
export BROKER_CONTROL_JWT_AUDIENCE="$JWT_AUDIENCE"
export BROKER_CONTROL_FRONTEND_ORIGIN="$FRONTEND_BASE_URL"
export BROKER_CONTROL_API_PORT="$API_PORT"
export BROKER_CONTROL_MQTT_PORT="$MQTT_PORT"
export BROKER_CONTROL_SECRETS_DIR="$SECRETS_DIR"
export BROKER_CONTROL_POSTGRES_VOLUME="${PROJECT_NAME}-postgres"
export BROKER_CONTROL_MQTT_VOLUME="${PROJECT_NAME}-mqtt"
export BROKER_CONTROL_NETWORK="${PROJECT_NAME}-network"
export BROKER_CONTROL_TELEMETRY_IMAGE="nexolab-telemetry-service:device-agent-fleet-acceptance"
export BROKER_CONTROL_MQTT_IMAGE="nexolab-mqtt-dynamic-security:device-agent-fleet-acceptance"
export FLEET_DEVICE_AGENT_IMAGE="nexolab-device-agent:fleet-acceptance"
export FLEET_EDGE_A_VOLUME="${PROJECT_NAME}-edge-a"
export FLEET_EDGE_B_VOLUME="${PROJECT_NAME}-edge-b"

compose() {
  local compose_args=(
    --project-name "$PROJECT_NAME"
    -f "$BASE_COMPOSE"
    -f "$FLEET_COMPOSE"
  )
  if [[ -n "$EXTRA_COMPOSE" ]]; then
    compose_args+=(-f "$EXTRA_COMPOSE")
  fi
  docker compose "${compose_args[@]}" "$@"
}

cleanup() {
  local status=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  compose ps --all >"$EVIDENCE_DIR/compose-ps.log" 2>&1 || true
  compose logs --no-color \
    postgres mqtt mqtt-policy-init telemetry-migrate telemetry-service \
    device-agent-a device-agent-b >"$SERVICE_LOG" 2>&1 || true
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT node_id, count(*) AS samples,
       min((raw_payload->>'node_sequence')::bigint) AS min_sequence,
       max((raw_payload->>'node_sequence')::bigint) AS max_sequence
FROM telemetry_samples
WHERE node_id IN ('edge-01', 'edge-02')
GROUP BY node_id
ORDER BY node_id;

SELECT n.node_id, h.health, h.queue_depth, h.node_sequence, h.received_at
FROM central_node_health_samples h
JOIN central_nodes n ON n.id = h.node_record_id
ORDER BY h.received_at DESC
LIMIT 20;

SELECT n.node_id, s.status, s.graceful, s.node_sequence, s.received_at
FROM central_node_status_events s
JOIN central_nodes n ON n.id = s.node_record_id
ORDER BY s.received_at DESC
LIMIT 20;

SELECT n.node_id, c.stream, c.last_sequence
FROM central_node_ingress_cursors c
JOIN central_nodes n ON n.id = c.node_record_id
WHERE n.node_id IN ('edge-01', 'edge-02')
ORDER BY n.node_id, c.stream;
SQL
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Device Agent fleet acceptance failed." >&2
    tail -n 320 "$SERVICE_LOG" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker curl python3 jq; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

generate_secret() {
  local path=$1
  local prefix=$2
  python3 - "$path" "$prefix" <<'PY'
from pathlib import Path
import secrets
import sys
path = Path(sys.argv[1])
path.write_text(sys.argv[2] + secrets.token_urlsafe(32), encoding="utf-8")
path.chmod(0o444)
PY
}

generate_encryption_key() {
  local path=$1
  python3 - "$path" <<'PY'
from pathlib import Path
import base64
import secrets
import sys
path = Path(sys.argv[1])
path.write_text(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"), encoding="ascii")
path.chmod(0o444)
PY
}

jwt_token() {
  python3 - "$JWT_SECRET" "$JWT_ISSUER" "$JWT_AUDIENCE" "$MANAGER_SUBJECT" <<'PY'
import base64
import hashlib
import hmac
import json
import sys
import time
secret, issuer, audience, subject = sys.argv[1:]
def encode(value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
now = int(time.time())
header = {"alg": "HS256", "typ": "JWT"}
payload = {
    "iss": issuer,
    "aud": audience,
    "sub": subject,
    "email": "manager-fleet@nexolab.local",
    "name": "Fleet Manager",
    "iat": now,
    "nbf": now - 5,
    "exp": now + 3600,
}
unsigned = f"{encode(header)}.{encode(payload)}"
signature = hmac.new(secret.encode(), unsigned.encode("ascii"), hashlib.sha256).digest()
print(f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}")
PY
}

api_get() {
  local path=$1
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${MANAGER_TOKEN}" \
    -H "X-Organization-ID: ${ORGANIZATION_ID}" \
    -H "Accept: application/json" \
    "${API_BASE_URL}${path}"
}

api_post() {
  local path=$1
  local payload=$2
  local idempotency_key=${3:-}
  local args=(
    --fail-with-body --silent --show-error
    -X POST
    -H "Authorization: Bearer ${MANAGER_TOKEN}"
    -H "X-Organization-ID: ${ORGANIZATION_ID}"
    -H "Accept: application/json"
    -H "Content-Type: application/json"
    --data "$payload"
  )
  if [[ -n "$idempotency_key" ]]; then
    args+=(-H "Idempotency-Key: ${idempotency_key}")
  fi
  curl "${args[@]}" "${API_BASE_URL}${path}"
}

wait_for_url() {
  local url=$1
  local label=$2
  for _ in $(seq 1 160); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

wait_for_broker() {
  for _ in $(seq 1 160); do
    if compose exec -T mqtt /usr/local/bin/nexolab-dynsec-admin list-clients \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for authenticated broker administration." >&2
  return 1
}

wait_for_control() {
  local node_id=$1
  local operation=$2
  for _ in $(seq 1 200); do
    if api_get "/api/v1/nodes/${node_id}/broker-control" \
      | jq -e --arg operation "$operation" \
        '.synchronization == "applied" and .latest_command.operation == $operation' \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${node_id} broker operation ${operation}." >&2
  return 1
}

agent_health() {
  local service=$1
  compose exec -T "$service" python - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=3) as response:
    print(json.dumps(json.load(response), separators=(",", ":")))
PY
}

queue_depth() {
  agent_health "$1" | jq -er '.queue_depth'
}

wait_for_agent() {
  local service=$1
  for _ in $(seq 1 160); do
    if agent_health "$service" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${service} health." >&2
  return 1
}

wait_queue_at_least() {
  local service=$1
  local minimum=$2
  local output=$3
  for _ in $(seq 1 200); do
    local depth
    depth="$(queue_depth "$service" 2>/dev/null || echo 0)"
    if (( depth >= minimum )); then
      agent_health "$service" >"$output"
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${service} queue >= ${minimum}." >&2
  return 1
}

wait_queue_zero() {
  local service=$1
  local output=$2
  for _ in $(seq 1 240); do
    if [[ "$(queue_depth "$service" 2>/dev/null || echo -1)" == "0" ]]; then
      agent_health "$service" >"$output"
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${service} queue drain." >&2
  return 1
}

telemetry_count() {
  local node_id=$1
  compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT count(*) FROM telemetry_samples WHERE node_id = '${node_id}';"
}

wait_telemetry_at_least() {
  local node_id=$1
  local minimum=$2
  for _ in $(seq 1 240); do
    if (( $(telemetry_count "$node_id") >= minimum )); then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${node_id} telemetry >= ${minimum}." >&2
  return 1
}

provision_node() {
  local node_id=$1
  local response
  response="$(api_post '/api/v1/nodes' \
    "{\"node_id\":\"${node_id}\",\"display_name\":\"Fleet ${node_id}\",\"clock_warning_ms\":30000,\"clock_critical_ms\":120000}" \
    "fleet-provision-${node_id}")"
  printf '%s' "$response" >"$PRIVATE_DIR/${node_id}-provision.json"
  printf '%s' "$response" | jq -er '.provisioning_secret' \
    >"$SECRETS_DIR/${node_id}-password"
  chmod 0444 "$SECRETS_DIR/${node_id}-password"
  wait_for_control "$node_id" provision
  api_post "/api/v1/nodes/${node_id}/activate" \
    '{"reason":"fleet acceptance commissioning"}' >/dev/null
}

wait_operational_online() {
  local node_id=$1
  local output=$2
  for _ in $(seq 1 200); do
    if api_get "/api/v1/nodes/${node_id}/operational-state" >"$output.tmp" 2>/dev/null \
      && jq -e '.availability == "online" and .latest_health.queue_depth == 0' \
        "$output.tmp" >/dev/null; then
      mv "$output.tmp" "$output"
      return 0
    fi
    sleep 0.25
  done
  mv "$output.tmp" "$output" 2>/dev/null || true
  echo "Timed out waiting for ${node_id} online operational state." >&2
  return 1
}

assert_database_invariants() {
  compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" <<'SQL'
DO $$
DECLARE
  duplicate_events integer;
  invalid_sequences integer;
  node_count integer;
BEGIN
  SELECT count(*) - count(DISTINCT event_id)
  INTO duplicate_events
  FROM telemetry_samples
  WHERE node_id IN ('edge-01', 'edge-02');
  IF duplicate_events <> 0 THEN
    RAISE EXCEPTION 'duplicate telemetry events found: %', duplicate_events;
  END IF;

  SELECT count(*) INTO node_count
  FROM (
    SELECT node_id
    FROM telemetry_samples
    WHERE node_id IN ('edge-01', 'edge-02')
    GROUP BY node_id
    HAVING min((raw_payload->>'node_sequence')::bigint) = 1
       AND max((raw_payload->>'node_sequence')::bigint) = count(*)
       AND count(DISTINCT (raw_payload->>'node_sequence')::bigint) = count(*)
  ) valid_nodes;
  IF node_count <> 2 THEN
    RAISE EXCEPTION 'expected contiguous independent telemetry sequences for two nodes';
  END IF;

  SELECT count(*) INTO invalid_sequences
  FROM central_node_ingress_cursors c
  JOIN central_nodes n ON n.id = c.node_record_id
  WHERE n.node_id IN ('edge-01', 'edge-02')
    AND c.stream = 'telemetry'
    AND c.last_sequence <= 0;
  IF invalid_sequences <> 0 THEN
    RAISE EXCEPTION 'invalid telemetry cursor state';
  END IF;
END
$$;
SQL
}

assert_no_plaintext_secrets() {
  local private_dump="$PRIVATE_DIR/database.dump"
  local private_logs="$PRIVATE_DIR/services.log"
  local private_inspect="$PRIVATE_DIR/containers.inspect"
  compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only \
    >"$private_dump"
  compose logs --no-color mqtt telemetry-service device-agent-a device-agent-b \
    >"$private_logs" 2>&1
  docker inspect \
    "${PROJECT_NAME}-device-agent-a-1" \
    "${PROJECT_NAME}-device-agent-b-1" >"$private_inspect"

  for secret_file in \
    admin-password ingestion-password edge-01-password edge-02-password edge-01-old-password; do
    local value
    value="$(tr -d '\r\n' <"$SECRETS_DIR/$secret_file")"
    if grep -Fq -- "$value" "$private_dump" \
      || grep -Fq -- "$value" "$private_logs" \
      || grep -Fq -- "$value" "$private_inspect"; then
      echo "Plaintext credential leaked into persistence, logs or container metadata." >&2
      return 1
    fi
    for service in device-agent-a device-agent-b; do
      if compose exec -T "$service" python - "$value" <<'PY'
from pathlib import Path
import sys
value = sys.argv[1].encode()
raise SystemExit(0 if value in Path('/var/lib/nexolab/edge.db').read_bytes() else 1)
PY
      then
        echo "Plaintext credential leaked into edge SQLite." >&2
        return 1
      fi
    done
  done
  printf '%s\n' \
    'postgres_plaintext=false' \
    'logs_plaintext=false' \
    'container_metadata_plaintext=false' \
    'edge_sqlite_plaintext=false' \
    >"$EVIDENCE_DIR/plaintext-check.txt"
}

rm -rf "$EVIDENCE_DIR" "$PRIVATE_DIR"
mkdir -p "$EVIDENCE_DIR" "$SECRETS_DIR"
chmod 0755 "$SECRETS_DIR"
if [[ -n "$SETUP_HOOK" ]]; then
  bash "$SETUP_HOOK" "$SECRETS_DIR" "$EVIDENCE_DIR"
fi
generate_secret "$SECRETS_DIR/admin-password" 'nxl_mqtt_admin_'
generate_secret "$SECRETS_DIR/ingestion-password" 'nxl_mqtt_ingestion_'
generate_encryption_key "$SECRETS_DIR/broker-control-key"

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose config --quiet
compose up -d --build postgres mqtt mqtt-policy-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "fleet telemetry service"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES ('$ORGANIZATION_ID', 'device-agent-fleet', 'Device Agent Fleet', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (
  id, provider, subject, email, display_name, is_active, last_authenticated_at
)
VALUES (
  '$MANAGER_ID', 'broker-control-acceptance', '$MANAGER_SUBJECT',
  'manager-fleet@nexolab.local', 'Fleet Manager', true, now()
)
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email,
    display_name = EXCLUDED.display_name,
    is_active = true,
    last_authenticated_at = EXCLUDED.last_authenticated_at;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES ('$MANAGER_MEMBERSHIP', '$ORGANIZATION_ID', '$MANAGER_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES ('$MANAGER_MEMBERSHIP', 'laboratory_manager', 'fleet-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL

MANAGER_TOKEN="$(jwt_token)"
provision_node "$NODE_A"
provision_node "$NODE_B"

compose up -d --build device-agent-a device-agent-b
wait_for_agent device-agent-a
wait_for_agent device-agent-b
wait_telemetry_at_least "$NODE_A" 5
wait_telemetry_at_least "$NODE_B" 5
wait_queue_zero device-agent-a "$EVIDENCE_DIR/edge-01-initial.json"
wait_queue_zero device-agent-b "$EVIDENCE_DIR/edge-02-initial.json"

compose stop mqtt
wait_queue_at_least device-agent-a 5 "$EVIDENCE_DIR/edge-01-outage.json"
wait_queue_at_least device-agent-b 5 "$EVIDENCE_DIR/edge-02-outage.json"
A_BEFORE_RESTART="$(queue_depth device-agent-a)"
B_BEFORE_RESTART="$(queue_depth device-agent-b)"
compose restart device-agent-a device-agent-b
wait_for_agent device-agent-a
wait_for_agent device-agent-b
wait_queue_at_least device-agent-a "$A_BEFORE_RESTART" \
  "$EVIDENCE_DIR/edge-01-restarted-outage.json"
wait_queue_at_least device-agent-b "$B_BEFORE_RESTART" \
  "$EVIDENCE_DIR/edge-02-restarted-outage.json"

compose start mqtt
wait_for_broker
wait_for_url "$API_BASE_URL/health/ready" "telemetry service after fleet recovery"
wait_queue_zero device-agent-a "$EVIDENCE_DIR/edge-01-recovered.json"
wait_queue_zero device-agent-b "$EVIDENCE_DIR/edge-02-recovered.json"
wait_operational_online "$NODE_A" "$EVIDENCE_DIR/edge-01-operational.json"
wait_operational_online "$NODE_B" "$EVIDENCE_DIR/edge-02-operational.json"

A_COUNT_BEFORE_ROTATION="$(telemetry_count "$NODE_A")"
B_COUNT_BEFORE_ROTATION="$(telemetry_count "$NODE_B")"
cp "$SECRETS_DIR/edge-01-password" "$SECRETS_DIR/edge-01-old-password"
chmod 0444 "$SECRETS_DIR/edge-01-old-password"
ROTATE_RESPONSE="$(api_post "/api/v1/nodes/${NODE_A}/credentials/rotate" \
  '{"reason":"fleet acceptance rotation"}' 'fleet-rotate-edge-01')"
printf '%s' "$ROTATE_RESPONSE" | jq -er '.provisioning_secret' \
  >"$SECRETS_DIR/edge-01-password-new"
chmod 0444 "$SECRETS_DIR/edge-01-password-new"
wait_for_control "$NODE_A" rotate

compose restart device-agent-a
wait_for_agent device-agent-a
wait_queue_at_least device-agent-a 3 "$EVIDENCE_DIR/edge-01-old-credential-rejected.json"
B_ROTATION_TARGET=$((B_COUNT_BEFORE_ROTATION + 3))
wait_telemetry_at_least "$NODE_B" "$B_ROTATION_TARGET"

mv "$SECRETS_DIR/edge-01-password-new" "$SECRETS_DIR/edge-01-password"
chmod 0444 "$SECRETS_DIR/edge-01-password"
compose restart device-agent-a
wait_for_agent device-agent-a
wait_queue_zero device-agent-a "$EVIDENCE_DIR/edge-01-rotated-recovered.json"
wait_telemetry_at_least "$NODE_A" $((A_COUNT_BEFORE_ROTATION + 3))
wait_operational_online "$NODE_A" "$EVIDENCE_DIR/edge-01-final-operational.json"
wait_operational_online "$NODE_B" "$EVIDENCE_DIR/edge-02-final-operational.json"

assert_database_invariants
assert_no_plaintext_secrets

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_ID"
export NEXT_TELEMETRY_DISABLED="1"
npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/nodes" "fleet operator UI"

export NEXOLAB_DEVICE_AGENT_FLEET_FRONTEND_URL="$FRONTEND_BASE_URL"
export NEXOLAB_DEVICE_AGENT_FLEET_ORGANIZATION_ID="$ORGANIZATION_ID"
export NEXOLAB_DEVICE_AGENT_FLEET_MANAGER_TOKEN="$MANAGER_TOKEN"
npx playwright test --config=playwright.device-agent-fleet.config.ts

printf '%s\n' \
  'secure_bootstrap=verified' \
  'two_actual_agents=verified' \
  'outage_queue_growth=verified' \
  'restart_queue_persistence=verified' \
  'fifo_backlog_drain=verified' \
  'independent_sequences=verified' \
  'zero_duplicate_events=verified' \
  'single_node_rotation=verified' \
  'unaffected_node_continuity=verified' \
  'operational_state_recovery=verified' \
  'browser_operator_state=verified' \
  'plaintext_credentials=absent' \
  >"$EVIDENCE_DIR/acceptance-summary.txt"

echo "Secure Device Agent fleet backlog acceptance passed."
