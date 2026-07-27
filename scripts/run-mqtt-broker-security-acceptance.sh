#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.mqtt-security-acceptance.yaml"
PROJECT_NAME="nexolab-mqtt-security-acceptance"
EVIDENCE_DIR="$ROOT_DIR/test-results-mqtt-security"
SECRETS_DIR="$EVIDENCE_DIR/secrets"
BROKER_LOG="$EVIDENCE_DIR/broker.log"

ADMIN_USERNAME="nexolab-security-admin"
INGESTION_USERNAME="nexolab-central-ingestion"
INGESTION_CLIENT_ID="nexolab-central-ingestion"
ORGANIZATION_A="00000000-0000-0000-0000-000000000001"
ORGANIZATION_B="00000000-0000-0000-0000-000000000002"
NODE_A="edge-01"
NODE_B="edge-02"
NODE_A_USERNAME="node:${ORGANIZATION_A}:${NODE_A}"
NODE_B_USERNAME="node:${ORGANIZATION_A}:${NODE_B}"
NODE_A_CLIENT_ID="nexolab-${ORGANIZATION_A}-${NODE_A}"
NODE_B_CLIENT_ID="nexolab-${ORGANIZATION_A}-${NODE_B}"
NODE_A_TOPIC="nexolab/v1/${ORGANIZATION_A}/${NODE_A}"
NODE_B_TOPIC="nexolab/v1/${ORGANIZATION_A}/${NODE_B}"
FOREIGN_TOPIC="nexolab/v1/${ORGANIZATION_B}/${NODE_A}/health"

export NEXOLAB_MQTT_ADMIN_USERNAME="$ADMIN_USERNAME"
export NEXOLAB_MQTT_SECURITY_SECRETS_DIR="$SECRETS_DIR"
export NEXOLAB_MQTT_SECURITY_PORT="${NEXOLAB_MQTT_SECURITY_PORT:-1889}"
export NEXOLAB_MQTT_SECURITY_VOLUME_NAME="${PROJECT_NAME}-data"
export NEXOLAB_MQTT_SECURITY_NETWORK_NAME="${PROJECT_NAME}-network"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

admin() {
  compose exec -T mqtt-security /usr/local/bin/nexolab-dynsec-admin "$@"
}

secret() {
  tr -d '\r\n' <"$SECRETS_DIR/$1"
}

mqtt_publish() {
  local username=$1
  local password=$2
  local client_id=$3
  local topic=$4
  local payload=$5
  local retain=${6:-false}
  local args=(
    exec -T mqtt-security mosquitto_pub
    -h 127.0.0.1 -p 1883
    -V mqttv5 -q 1 --quiet
    -u "$username" -P "$password" -i "$client_id"
    -t "$topic" -m "$payload"
  )
  if [[ "$retain" == "true" ]]; then
    args+=(--retain)
  fi
  compose "${args[@]}"
}

mqtt_subscribe_once() {
  local username=$1
  local password=$2
  local client_id=$3
  local topic=$4
  compose exec -T mqtt-security mosquitto_sub \
    -h 127.0.0.1 -p 1883 \
    -V mqttv5 -q 1 --quiet \
    -u "$username" -P "$password" -i "$client_id" \
    -C 1 -W 5 -t "$topic"
}

expect_denied() {
  local label=$1
  shift
  if "$@" >"$EVIDENCE_DIR/${label}.log" 2>&1; then
    echo "Expected broker denial but command succeeded: $label" >&2
    return 1
  fi
}

expect_no_subscription_delivery() {
  local label=$1
  local username=$2
  local password=$3
  local client_id=$4
  local topic=$5
  local output
  local exit_code

  set +e
  output="$(mqtt_subscribe_once "$username" "$password" "$client_id" "$topic" \
    2>"$EVIDENCE_DIR/${label}.log")"
  exit_code=$?
  set -e
  printf 'exit_code=%s\n' "$exit_code" >>"$EVIDENCE_DIR/${label}.log"
  if [[ -n "$output" ]]; then
    printf 'unexpected_payload=%s\n' "$output" >>"$EVIDENCE_DIR/${label}.log"
    echo "Denied subscription received a payload: $label" >&2
    return 1
  fi
}

attempt_forbidden_publish() {
  local label=$1
  local username=$2
  local password=$3
  local client_id=$4
  local topic=$5
  local payload=$6
  mqtt_publish "$username" "$password" "$client_id" "$topic" "$payload" true \
    >"$EVIDENCE_DIR/${label}.log" 2>&1 || true
}

assert_retained_equals() {
  local label=$1
  local topic=$2
  local expected=$3
  local received
  received="$(mqtt_subscribe_once "$INGESTION_USERNAME" "$INGESTION_PASSWORD" \
    "$INGESTION_CLIENT_ID" "$topic")"
  if [[ "$received" != "$expected" ]]; then
    printf 'expected=%s\nreceived=%s\n' "$expected" "$received" \
      >"$EVIDENCE_DIR/${label}.log"
    echo "Retained payload changed unexpectedly: $label" >&2
    return 1
  fi
  printf 'retained=%s\n' "$received" >"$EVIDENCE_DIR/${label}.log"
}

expect_no_retained() {
  local label=$1
  local topic=$2
  local output
  local exit_code

  set +e
  output="$(mqtt_subscribe_once "$INGESTION_USERNAME" "$INGESTION_PASSWORD" \
    "$INGESTION_CLIENT_ID" "$topic" \
    2>"$EVIDENCE_DIR/${label}.log")"
  exit_code=$?
  set -e
  printf 'exit_code=%s\n' "$exit_code" >>"$EVIDENCE_DIR/${label}.log"
  if [[ -n "$output" ]]; then
    printf 'unexpected_payload=%s\n' "$output" >>"$EVIDENCE_DIR/${label}.log"
    echo "Forbidden publish created a retained message: $label" >&2
    return 1
  fi
}

wait_for_broker() {
  for _ in $(seq 1 60); do
    if admin list-clients >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for authenticated broker administration." >&2
  return 1
}

generate_secret() {
  local path=$1
  python3 - "$path" <<'PY'
from pathlib import Path
import secrets
import sys

path = Path(sys.argv[1])
path.write_text("nxl_mqtt_" + secrets.token_urlsafe(32))
path.chmod(0o600)
PY
}

validate_dynamic_security_state() {
  compose exec -T mqtt-security sh -s <<'SH'
set -eu

config=/mosquitto/data/dynamic-security.json
[ -s "$config" ]

for secret_file in \
  /run/secrets/nexolab/admin-password \
  /run/secrets/nexolab/ingestion-password \
  /run/secrets/nexolab/node-a-old \
  /run/secrets/nexolab/node-a-new \
  /run/secrets/nexolab/node-b-password; do
  secret_value="$(tr -d '\r\n' <"$secret_file")"
  [ -n "$secret_value" ]
  if grep -Fq -- "$secret_value" "$config"; then
    echo "Plaintext secret leaked into dynamic-security.json" >&2
    exit 1
  fi
done

for username in \
  nexolab-security-admin \
  nexolab-central-ingestion \
  node:00000000-0000-0000-0000-000000000001:edge-01 \
  node:00000000-0000-0000-0000-000000000001:edge-02; do
  jq -e --arg username "$username" \
    '.clients[] | select(.username == $username)' \
    "$config" >/dev/null
done

jq -e \
  '.clients[] | select(
    .username == "node:00000000-0000-0000-0000-000000000001:edge-02"
    and .disabled == true
  )' \
  "$config" >/dev/null

for role_name in \
  nexolab-central-ingestion \
  nexolab-node-00000000-0000-0000-0000-000000000001-edge-01 \
  nexolab-node-00000000-0000-0000-0000-000000000001-edge-02; do
  jq -e --arg role_name "$role_name" \
    '.roles[] | select(.rolename == $role_name)' \
    "$config" >/dev/null
done
SH
}

cleanup() {
  local status=$?
  set +e
  compose logs --no-color mqtt-security >"$BROKER_LOG" 2>&1 || true
  compose ps --all >"$EVIDENCE_DIR/compose-ps.log" 2>&1 || true
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$SECRETS_DIR"
  if [[ $status -ne 0 ]]; then
    echo "MQTT broker security acceptance failed." >&2
    tail -n 240 "$BROKER_LOG" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker python3; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

rm -rf "$EVIDENCE_DIR"
mkdir -p "$SECRETS_DIR"
chmod 0700 "$SECRETS_DIR"
for name in admin-password ingestion-password node-a-old node-a-new node-b-password unknown-password; do
  generate_secret "$SECRETS_DIR/$name"
done

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up -d --build mqtt-security
wait_for_broker

admin bootstrap-defaults
admin create-ingestion \
  "$INGESTION_USERNAME" \
  "$INGESTION_CLIENT_ID" \
  /run/secrets/nexolab/ingestion-password
admin create-node \
  "$NODE_A_USERNAME" \
  "$NODE_A_CLIENT_ID" \
  "$ORGANIZATION_A" \
  "$NODE_A" \
  /run/secrets/nexolab/node-a-old
admin create-node \
  "$NODE_B_USERNAME" \
  "$NODE_B_CLIENT_ID" \
  "$ORGANIZATION_A" \
  "$NODE_B" \
  /run/secrets/nexolab/node-b-password

INGESTION_PASSWORD="$(secret ingestion-password)"
NODE_A_OLD_PASSWORD="$(secret node-a-old)"
NODE_A_NEW_PASSWORD="$(secret node-a-new)"
NODE_B_PASSWORD="$(secret node-b-password)"
UNKNOWN_PASSWORD="$(secret unknown-password)"

expect_denied anonymous-connect \
  compose exec -T mqtt-security mosquitto_pub \
    -h 127.0.0.1 -p 1883 -V mqttv5 -q 1 --quiet \
    -i anonymous-client -t "$NODE_A_TOPIC/health" -m anonymous
expect_denied unknown-client \
  mqtt_publish unknown-client "$UNKNOWN_PASSWORD" unknown-client "$NODE_A_TOPIC/health" unknown
expect_denied client-id-mismatch \
  mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" wrong-client-id "$NODE_A_TOPIC/health" wrong-id

mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/telemetry" '{"source":"node-a-telemetry"}' true
mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/health" '{"source":"node-a-health"}' true
mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/status" '{"source":"node-a-status"}' true
mqtt_publish "$NODE_B_USERNAME" "$NODE_B_PASSWORD" "$NODE_B_CLIENT_ID" \
  "$NODE_B_TOPIC/health" '{"source":"node-b-health"}' true

assert_retained_equals authorized-node-a-health \
  "$NODE_A_TOPIC/health" '{"source":"node-a-health"}'

attempt_forbidden_publish node-foreign-node-topic \
  "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_B_TOPIC/health" foreign-node
assert_retained_equals node-foreign-node-not-delivered \
  "$NODE_B_TOPIC/health" '{"source":"node-b-health"}'

attempt_forbidden_publish node-foreign-organization-topic \
  "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$FOREIGN_TOPIC" foreign-organization
expect_no_retained node-foreign-organization-not-delivered "$FOREIGN_TOPIC"

expect_no_subscription_delivery node-subscription \
  "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/health"
expect_no_subscription_delivery node-sys-subscription \
  "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" '$SYS/#'

attempt_forbidden_publish ingestion-publish \
  "$INGESTION_USERNAME" "$INGESTION_PASSWORD" "$INGESTION_CLIENT_ID" \
  "$NODE_A_TOPIC/health" ingestion-must-not-publish
assert_retained_equals ingestion-publish-not-delivered \
  "$NODE_A_TOPIC/health" '{"source":"node-a-health"}'

admin rotate-password "$NODE_A_USERNAME" /run/secrets/nexolab/node-a-new
expect_denied rotated-old-password \
  mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
    "$NODE_A_TOPIC/health" old-password
mqtt_publish "$NODE_A_USERNAME" "$NODE_A_NEW_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/health" '{"source":"node-a-rotated"}' true

admin disable-client "$NODE_B_USERNAME"
expect_denied disabled-node \
  mqtt_publish "$NODE_B_USERNAME" "$NODE_B_PASSWORD" "$NODE_B_CLIENT_ID" \
    "$NODE_B_TOPIC/health" disabled

admin get-client "$NODE_A_USERNAME" >"$EVIDENCE_DIR/node-a-client.txt"
admin get-client "$NODE_B_USERNAME" >"$EVIDENCE_DIR/node-b-client.txt"
admin list-clients >"$EVIDENCE_DIR/client-list.txt"
validate_dynamic_security_state

compose restart mqtt-security
wait_for_broker

mqtt_publish "$NODE_A_USERNAME" "$NODE_A_NEW_PASSWORD" "$NODE_A_CLIENT_ID" \
  "$NODE_A_TOPIC/status" '{"source":"after-restart"}' true
expect_denied restart-old-password \
  mqtt_publish "$NODE_A_USERNAME" "$NODE_A_OLD_PASSWORD" "$NODE_A_CLIENT_ID" \
    "$NODE_A_TOPIC/status" old-after-restart
expect_denied restart-disabled-node \
  mqtt_publish "$NODE_B_USERNAME" "$NODE_B_PASSWORD" "$NODE_B_CLIENT_ID" \
    "$NODE_B_TOPIC/status" disabled-after-restart

assert_retained_equals restart-status-delivery \
  "$NODE_A_TOPIC/status" '{"source":"after-restart"}'

printf '%s\n' \
  "anonymous=denied" \
  "unknown=denied" \
  "client_id_binding=enforced" \
  "node_exact_publish=allowed" \
  "foreign_publish=not_delivered" \
  "node_subscribe=no_delivery" \
  "ingestion_subscribe=allowed" \
  "ingestion_publish=not_delivered" \
  "password_rotation=enforced" \
  "disabled_client=denied" \
  "restart_persistence=verified" \
  "plaintext_secrets=absent" \
  >"$EVIDENCE_DIR/acceptance-summary.txt"
