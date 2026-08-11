#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.broker-control-acceptance.yaml"
PROJECT_NAME="nexolab-broker-control-acceptance"
EVIDENCE_DIR="$ROOT_DIR/test-results-broker-control"
PRIVATE_DIR="${TMPDIR:-/tmp}/${PROJECT_NAME}-private"
SECRETS_DIR="$PRIVATE_DIR/secrets"
FRONTEND_LOG="$EVIDENCE_DIR/frontend.log"
SERVICE_LOG="$EVIDENCE_DIR/services.log"
FRONTEND_PID=""
LIVE_CONNECTION_PID=""
LIVE_CONNECTION_FIFO=""

API_PORT="${BROKER_CONTROL_API_PORT:-8091}"
MQTT_PORT="${BROKER_CONTROL_MQTT_PORT:-1891}"
FRONTEND_PORT="${BROKER_CONTROL_FRONTEND_PORT:-3110}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"

POSTGRES_DB="nexolab"
POSTGRES_USER="nexolab"
POSTGRES_PASSWORD="broker-control-postgres-secret"
ADMIN_USERNAME="nexolab-security-admin"
INGESTION_USERNAME="nexolab-central-ingestion"
INGESTION_CLIENT_ID="nexolab-central-ingestion"
ORGANIZATION_A="00000000-0000-0000-0000-000000000001"
ORGANIZATION_B="00000000-0000-0000-0000-000000000002"
MANAGER_A_ID="41000000-0000-0000-0000-000000000011"
MANAGER_B_ID="41000000-0000-0000-0000-000000000012"
MANAGER_A_MEMBERSHIP="51000000-0000-0000-0000-000000000011"
MANAGER_B_MEMBERSHIP="51000000-0000-0000-0000-000000000012"
MANAGER_A_SUBJECT="manager-a-broker-control-acceptance"
MANAGER_B_SUBJECT="manager-b-broker-control-acceptance"
JWT_SECRET="broker-control-browser-acceptance-secret-with-at-least-thirty-two-bytes"
JWT_ISSUER="https://auth.nexolab.local/broker-control-acceptance"
JWT_AUDIENCE="nexolab-broker-control-acceptance"
NODE_ID="edge-01"
NODE_USERNAME="node:${ORGANIZATION_A}:${NODE_ID}"
NODE_CLIENT_ID="nexolab-${ORGANIZATION_A}-${NODE_ID}"
NODE_TOPIC="nexolab/v1/${ORGANIZATION_A}/${NODE_ID}"

export POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export NEXOLAB_MQTT_ADMIN_USERNAME="$ADMIN_USERNAME"
export BROKER_CONTROL_INGESTION_USERNAME="$INGESTION_USERNAME"
export BROKER_CONTROL_INGESTION_CLIENT_ID="$INGESTION_CLIENT_ID"
export BROKER_CONTROL_ORGANIZATION_A="$ORGANIZATION_A"
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
export BROKER_CONTROL_TELEMETRY_IMAGE="nexolab-telemetry-service:broker-control-acceptance"
export BROKER_CONTROL_MQTT_IMAGE="nexolab-mqtt-dynamic-security:broker-control-acceptance"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup_live_connection() {
  set +e
  if [[ -n "$LIVE_CONNECTION_PID" ]]; then
    kill "$LIVE_CONNECTION_PID" >/dev/null 2>&1 || true
    wait "$LIVE_CONNECTION_PID" >/dev/null 2>&1 || true
    LIVE_CONNECTION_PID=""
  fi
  exec 9>&- 2>/dev/null || true
  if [[ -n "$LIVE_CONNECTION_FIFO" ]]; then
    rm -f "$LIVE_CONNECTION_FIFO"
    LIVE_CONNECTION_FIFO=""
  fi
  set -e
}

cleanup() {
  local status=$?
  set +e
  cleanup_live_connection
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  compose ps --all >"$EVIDENCE_DIR/compose-ps.log" 2>&1 || true
  compose logs --no-color postgres mqtt mqtt-policy-init telemetry-migrate telemetry-service \
    >"$SERVICE_LOG" 2>&1 || true
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT n.organization_id, n.node_id, n.state, n.state_reason,
       c.generation, c.secret_fingerprint, c.revoked_at
FROM central_nodes n
LEFT JOIN central_node_credentials c ON c.node_record_id = n.id
ORDER BY n.organization_id, n.node_id, c.generation;

SELECT organization_id, node_id, operation, state, attempts,
       available_at, last_attempt_at, applied_at, failed_at,
       error_code, error_detail, created_at, updated_at
FROM central_node_broker_commands
ORDER BY created_at, id;

SELECT organization_id, action, entity_type, actor_subject, reason, occurred_at
FROM security_audit_events
WHERE entity_type = 'central_node'
ORDER BY occurred_at, id;
SQL
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Broker-control acceptance failed." >&2
    tail -n 220 "$FRONTEND_LOG" >&2 || true
    tail -n 300 "$SERVICE_LOG" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker npm curl python3 jq; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

wait_for_url() {
  local url=$1
  local label=$2
  for _ in $(seq 1 120); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

wait_for_broker() {
  for _ in $(seq 1 120); do
    if compose exec -T mqtt /usr/local/bin/nexolab-dynsec-admin list-clients \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "Timed out waiting for authenticated broker administration." >&2
  return 1
}

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
  local subject=$1
  local email=$2
  local display_name=$3
  python3 - "$JWT_SECRET" "$JWT_ISSUER" "$JWT_AUDIENCE" "$subject" "$email" "$display_name" <<'PY'
import base64
import hashlib
import hmac
import json
import sys
import time
secret, issuer, audience, subject, email, display_name = sys.argv[1:]
def encode(value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
now = int(time.time())
header = {"alg": "HS256", "typ": "JWT"}
payload = {
    "iss": issuer,
    "aud": audience,
    "sub": subject,
    "email": email,
    "name": display_name,
    "iat": now,
    "nbf": now - 5,
    "exp": now + 3600,
}
unsigned = f"{encode(header)}.{encode(payload)}"
signature = hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256).digest()
print(f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}")
PY
}

api_get() {
  local path=$1
  local token=$2
  local organization=$3
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${token}" \
    -H "X-Organization-ID: ${organization}" \
    -H "Accept: application/json" \
    "${API_BASE_URL}${path}"
}

api_post() {
  local path=$1
  local token=$2
  local organization=$3
  local payload=$4
  local idempotency_key=${5:-}
  local args=(
    --fail-with-body --silent --show-error
    -X POST
    -H "Authorization: Bearer ${token}"
    -H "X-Organization-ID: ${organization}"
    -H "Accept: application/json"
    -H "Content-Type: application/json"
    --data "$payload"
  )
  if [[ -n "$idempotency_key" ]]; then
    args+=(-H "Idempotency-Key: ${idempotency_key}")
  fi
  curl "${args[@]}" "${API_BASE_URL}${path}"
}

wait_for_control() {
  local token=$1
  local synchronization=$2
  local operation=$3
  local output=$4
  for _ in $(seq 1 160); do
    if api_get "/api/v1/nodes/${NODE_ID}/broker-control" "$token" "$ORGANIZATION_A" \
      >"$output.tmp" 2>/dev/null; then
      if jq -e \
        --arg synchronization "$synchronization" \
        --arg operation "$operation" \
        '.synchronization == $synchronization and .latest_command.operation == $operation' \
        "$output.tmp" >/dev/null; then
        mv "$output.tmp" "$output"
        return 0
      fi
    fi
    sleep 0.25
  done
  mv "$output.tmp" "$output" 2>/dev/null || true
  echo "Timed out waiting for broker control ${operation}/${synchronization}." >&2
  return 1
}

create_node_options() {
  local output_name=$1
  local password_file=$2
  local password
  password="$(tr -d '\r\n' <"$password_file")"
  {
    printf '%s\n' '-h 127.0.0.1'
    printf '%s\n' '-p 1883'
    printf '%s\n' "-i ${NODE_CLIENT_ID}"
    printf '%s\n' "-u ${NODE_USERNAME}"
    printf '%s\n' "-P ${password}"
    printf '%s\n' '--quiet'
  } >"$SECRETS_DIR/$output_name"
  chmod 0444 "$SECRETS_DIR/$output_name"
  unset password
}

mqtt_publish() {
  local options_name=$1
  local stream=$2
  local payload=$3
  compose exec -T mqtt mosquitto_pub \
    -o "/run/secrets/nexolab/${options_name}" \
    -V mqttv5 -q 1 \
    -t "${NODE_TOPIC}/${stream}" \
    -m "$payload"
}

expect_mqtt_denied() {
  local label=$1
  local options_name=$2
  if mqtt_publish "$options_name" health denied \
    >"$EVIDENCE_DIR/${label}.log" 2>&1; then
    echo "Expected MQTT authentication denial: $label" >&2
    return 1
  fi
}

start_live_connection() {
  cleanup_live_connection
  LIVE_CONNECTION_FIFO="$EVIDENCE_DIR/node-live-input"
  rm -f "$LIVE_CONNECTION_FIFO"
  mkfifo "$LIVE_CONNECTION_FIFO"
  exec 9<>"$LIVE_CONNECTION_FIFO"
  compose exec -T mqtt mosquitto_pub \
    -o /run/secrets/nexolab/node-new.options \
    -V mqttv5 -q 1 \
    -t "${NODE_TOPIC}/telemetry" \
    -l <"$LIVE_CONNECTION_FIFO" \
    >"$EVIDENCE_DIR/node-live-connection.log" 2>&1 &
  LIVE_CONNECTION_PID=$!
  sleep 1
  if ! kill -0 "$LIVE_CONNECTION_PID" >/dev/null 2>&1; then
    wait "$LIVE_CONNECTION_PID" || true
    echo "Live node MQTT connection did not remain active." >&2
    return 1
  fi
}

assert_administrative_disconnect() {
  local label=$1
  local evidence="Client ${NODE_CLIENT_ID} been disconnected by administrative action."
  for _ in $(seq 1 80); do
    if compose logs --no-color mqtt 2>&1 | grep -Fq -- "$evidence"; then
      printf 'administrative_disconnect=true\n' >"$EVIDENCE_DIR/${label}.log"
      cleanup_live_connection
      return 0
    fi
    sleep 0.25
  done
  echo "Broker did not record administrative disconnect: $label" >&2
  return 1
}

assert_no_plaintext_secrets() {
  local private_dump="$PRIVATE_DIR/database.dump"
  local private_logs="$PRIVATE_DIR/services.log"
  compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --data-only \
    >"$private_dump"
  compose logs --no-color mqtt mqtt-policy-init telemetry-service >"$private_logs" 2>&1

  for secret_file in admin-password ingestion-password node-old-password node-new-password; do
    local value
    value="$(tr -d '\r\n' <"$SECRETS_DIR/$secret_file")"
    if grep -Fq -- "$value" "$private_dump" || grep -Fq -- "$value" "$private_logs"; then
      echo "Plaintext secret leaked into database or logs: $secret_file" >&2
      return 1
    fi
  done

  compose exec -T mqtt sh -s <<'SH'
set -eu
config=/mosquitto/data/dynamic-security.json
for secret_file in \
  /run/secrets/nexolab/admin-password \
  /run/secrets/nexolab/ingestion-password \
  /run/secrets/nexolab/node-old-password \
  /run/secrets/nexolab/node-new-password; do
  value="$(tr -d '\r\n' <"$secret_file")"
  if grep -Fq -- "$value" "$config"; then
    echo "Plaintext secret leaked into dynamic-security persistence" >&2
    exit 1
  fi
done
SH
  printf '%s\n' \
    'postgres_plaintext=false' \
    'logs_plaintext=false' \
    'dynamic_security_plaintext=false' \
    >"$EVIDENCE_DIR/plaintext-check.txt"
}

rm -rf "$EVIDENCE_DIR" "$PRIVATE_DIR" "$ROOT_DIR/playwright-report-broker-control"
mkdir -p "$EVIDENCE_DIR" "$SECRETS_DIR"
chmod 0755 "$SECRETS_DIR"
generate_secret "$SECRETS_DIR/admin-password" 'nxl_mqtt_admin_'
generate_secret "$SECRETS_DIR/ingestion-password" 'nxl_mqtt_ingestion_'
generate_encryption_key "$SECRETS_DIR/broker-control-key"

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose config --quiet
compose up -d --build postgres mqtt mqtt-policy-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "broker-control telemetry service"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  ('$ORGANIZATION_A', 'broker-control-org-a', 'Broker Control Organization A', true),
  ('$ORGANIZATION_B', 'broker-control-org-b', 'Broker Control Organization B', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (
  id, provider, subject, email, display_name, is_active, last_authenticated_at
)
VALUES
  ('$MANAGER_A_ID', 'broker-control-acceptance', '$MANAGER_A_SUBJECT', 'manager-a-broker@nexolab.local', 'Manager A Broker', true, now()),
  ('$MANAGER_B_ID', 'broker-control-acceptance', '$MANAGER_B_SUBJECT', 'manager-b-broker@nexolab.local', 'Manager B Broker', true, now())
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email,
    display_name = EXCLUDED.display_name,
    is_active = true,
    last_authenticated_at = EXCLUDED.last_authenticated_at;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('$MANAGER_A_MEMBERSHIP', '$ORGANIZATION_A', '$MANAGER_A_ID', true),
  ('$MANAGER_B_MEMBERSHIP', '$ORGANIZATION_B', '$MANAGER_B_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('$MANAGER_A_MEMBERSHIP', 'laboratory_manager', 'broker-control-acceptance'),
  ('$MANAGER_B_MEMBERSHIP', 'laboratory_manager', 'broker-control-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  < "$ROOT_DIR/scripts/security-acceptance-role-permissions.sql"

MANAGER_A_TOKEN="$(jwt_token "$MANAGER_A_SUBJECT" 'manager-a-broker@nexolab.local' 'Manager A Broker')"
MANAGER_B_TOKEN="$(jwt_token "$MANAGER_B_SUBJECT" 'manager-b-broker@nexolab.local' 'Manager B Broker')"

compose stop mqtt
sleep 1

PROVISION_PAYLOAD='{"node_id":"edge-01","display_name":"Broker Control Edge","clock_warning_ms":30000,"clock_critical_ms":120000}'
PROVISION_RESPONSE="$(api_post '/api/v1/nodes' "$MANAGER_A_TOKEN" "$ORGANIZATION_A" "$PROVISION_PAYLOAD" 'broker-control-provision-edge-01')"
printf '%s' "$PROVISION_RESPONSE" >"$PRIVATE_DIR/provision-response.json"
printf '%s' "$PROVISION_RESPONSE" | jq -er '.provisioning_secret' >"$SECRETS_DIR/node-old-password"
chmod 0444 "$SECRETS_DIR/node-old-password"

REPLAY_RESPONSE="$(api_post '/api/v1/nodes' "$MANAGER_A_TOKEN" "$ORGANIZATION_A" "$PROVISION_PAYLOAD" 'broker-control-provision-edge-01')"
printf '%s' "$REPLAY_RESPONSE" | jq -e '.replayed == true and .provisioning_secret == null' >/dev/null
wait_for_control "$MANAGER_A_TOKEN" retrying provision "$EVIDENCE_DIR/provision-retrying.json"

COMMAND_COUNT="$(compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM central_node_broker_commands WHERE node_id = '${NODE_ID}';")"
[[ "$COMMAND_COUNT" == "1" ]]

compose restart telemetry-service
wait_for_url "$API_BASE_URL/health/live" "telemetry service after restart"
compose start mqtt
wait_for_broker
wait_for_url "$API_BASE_URL/health/ready" "telemetry service after broker recovery"
wait_for_control "$MANAGER_A_TOKEN" applied provision "$EVIDENCE_DIR/provision-applied.json"

create_node_options node-old.options "$SECRETS_DIR/node-old-password"
api_post "/api/v1/nodes/${NODE_ID}/activate" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"commissioning approved"}' >/dev/null
mqtt_publish node-old.options health '{"health":"credential-valid"}'

ROTATE_RESPONSE="$(api_post "/api/v1/nodes/${NODE_ID}/credentials/rotate" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"scheduled rotation"}' 'broker-control-rotate-edge-01-2')"
printf '%s' "$ROTATE_RESPONSE" | jq -er '.provisioning_secret' >"$SECRETS_DIR/node-new-password"
chmod 0444 "$SECRETS_DIR/node-new-password"
create_node_options node-new.options "$SECRETS_DIR/node-new-password"
wait_for_control "$MANAGER_A_TOKEN" applied rotate "$EVIDENCE_DIR/rotate-applied.json"
expect_mqtt_denied rotated-old-password node-old.options
mqtt_publish node-new.options health '{"health":"rotated-credential-valid"}'

ROTATE_REPLAY="$(api_post "/api/v1/nodes/${NODE_ID}/credentials/rotate" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"scheduled rotation"}' 'broker-control-rotate-edge-01-2')"
printf '%s' "$ROTATE_REPLAY" | jq -e '.replayed == true and .provisioning_secret == null' >/dev/null

start_live_connection
api_post "/api/v1/nodes/${NODE_ID}/suspend" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"maintenance"}' >/dev/null
wait_for_control "$MANAGER_A_TOKEN" applied disable "$EVIDENCE_DIR/disable-applied.json"
assert_administrative_disconnect suspend-active-client
expect_mqtt_denied suspended-client node-new.options

api_post "/api/v1/nodes/${NODE_ID}/activate" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"maintenance complete"}' >/dev/null
wait_for_control "$MANAGER_A_TOKEN" applied enable "$EVIDENCE_DIR/enable-applied.json"
mqtt_publish node-new.options status '{"status":"reactivated"}'

start_live_connection
api_post "/api/v1/nodes/${NODE_ID}/revoke" "$MANAGER_A_TOKEN" "$ORGANIZATION_A" \
  '{"reason":"node retired"}' >/dev/null
wait_for_control "$MANAGER_A_TOKEN" applied delete "$EVIDENCE_DIR/delete-applied.json"
assert_administrative_disconnect revoke-active-client
expect_mqtt_denied revoked-client node-new.options

if compose exec -T mqtt /usr/local/bin/nexolab-dynsec-admin list-clients \
  | grep -Fqx -- "$NODE_USERNAME"; then
  echo "Revoked broker client still exists." >&2
  exit 1
fi

FOREIGN_STATUS="$(curl --silent --output "$EVIDENCE_DIR/foreign-organization.json" --write-out '%{http_code}' \
  -H "Authorization: Bearer ${MANAGER_B_TOKEN}" \
  -H "X-Organization-ID: ${ORGANIZATION_B}" \
  -H 'Accept: application/json' \
  "${API_BASE_URL}/api/v1/nodes/${NODE_ID}/broker-control")"
[[ "$FOREIGN_STATUS" == "404" ]]

COMMAND_COUNT="$(compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT count(*) FROM central_node_broker_commands WHERE node_id = '${NODE_ID}';")"
[[ "$COMMAND_COUNT" == "5" ]]
compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT operation || '=' || state FROM central_node_broker_commands WHERE node_id = '${NODE_ID}' ORDER BY created_at, id;" \
  >"$EVIDENCE_DIR/command-states.txt"
for expected in provision=applied rotate=applied disable=applied enable=applied delete=applied; do
  grep -Fqx -- "$expected" "$EVIDENCE_DIR/command-states.txt"
done

assert_no_plaintext_secrets

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_A"
export NEXT_TELEMETRY_DISABLED="1"
npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/nodes" "broker-control operator UI"

export NEXOLAB_BROKER_CONTROL_FRONTEND_URL="$FRONTEND_BASE_URL"
export NEXOLAB_BROKER_CONTROL_ORGANIZATION_ID="$ORGANIZATION_A"
export NEXOLAB_BROKER_CONTROL_MANAGER_TOKEN="$MANAGER_A_TOKEN"
npx playwright test --config=playwright.broker-control.config.ts

printf '%s\n' \
  'outage_retry=verified' \
  'service_restart_recovery=verified' \
  'provision_idempotency=verified' \
  'password_rotation=verified' \
  'suspension_disconnect=verified' \
  'reactivation_enable=verified' \
  'revocation_delete=verified' \
  'organization_isolation=verified' \
  'browser_reconciliation=verified' \
  'plaintext_secrets=absent' \
  >"$EVIDENCE_DIR/acceptance-summary.txt"

echo "Broker-control PostgreSQL, secure Mosquitto and browser acceptance passed."
