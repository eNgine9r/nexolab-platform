#!/usr/bin/env bash
# #1762 slices 3-4: isolated committed-receipt end-to-end acceptance.
#
# Disposable GitHub Actions fixture: Mosquitto Dynamic Security with the
# dedicated receipt identities, PostgreSQL 16, telemetry-service with
# NEXOLAB_COMMITTED_RECEIPTS=enabled and one Device Agent with
# DEVICE_AGENT_COMMITTED_RECEIPTS=enabled in simulator mode. No Modbus, no
# serial device, no hardware, no production broker or database. Every secret is
# generated at runtime and deleted on exit.
#
# Scenario: steady flow -> central ingestion outage that overflows a tiny
# broker queue (drop after PUBACK, the 2026-11-25 loss class) with a fast
# simulated backlog -> forged, wrong-node, wrong-sequence, unknown-row and
# duplicate receipts -> Edge restart during the outage -> central restart with
# bounded bulk catch-up while live flow continues (#1762 slice 4 throughput
# gate) -> Edge restart mid-catch-up -> drain to zero -> exact PostgreSQL
# accounting. Recovery throughput is written to $EVIDENCE_DIR/summary.md and
# summary.json.
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.broker-control-acceptance.yaml"
RECEIPT_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.committed-receipt-acceptance.yaml"
BROKER_CONFIG_SOURCE="$ROOT_DIR/infrastructure/mqtt/dynamic-security/mosquitto.conf"
PROJECT_NAME="${RECEIPT_E2E_PROJECT_NAME:-nexolab-committed-receipt-acceptance}"
EVIDENCE_DIR="${RECEIPT_E2E_EVIDENCE_DIR:-$ROOT_DIR/test-results-committed-receipt}"
PRIVATE_DIR="${TMPDIR:-/tmp}/${PROJECT_NAME}-private"
SECRETS_DIR="$PRIVATE_DIR/secrets"
SERVICE_LOG="$EVIDENCE_DIR/services.log"
TIMELINE="$EVIDENCE_DIR/timeline.log"

# Bounded scenario parameters (the job must finish well under 15 minutes).
QUEUE_CAP="${RECEIPT_E2E_QUEUE_CAP:-10}"
LIVE_INTERVAL="${RECEIPT_E2E_LIVE_INTERVAL_SECONDS:-0.25}"
# Fast simulated sampling during the outage builds a large backlog quickly.
OUTAGE_INTERVAL="${RECEIPT_E2E_OUTAGE_INTERVAL_SECONDS:-0.04}"
# Live flow during catch-up (about the 4.5 rows/s of the 2026-11-25 site).
RECOVERY_INTERVAL="${RECEIPT_E2E_RECOVERY_INTERVAL_SECONDS:-0.25}"
REPLAY_AFTER="${RECEIPT_E2E_REPLAY_AFTER_SECONDS:-5}"
STEADY_MIN_ROWS="${RECEIPT_E2E_STEADY_MIN_ROWS:-10}"
OUTAGE_MIN_PENDING="${RECEIPT_E2E_OUTAGE_MIN_PENDING:-1200}"
STEADY_MAX_PENDING="${RECEIPT_E2E_STEADY_MAX_PENDING:-12}"
CATCHUP_WINDOW_SECONDS="${RECEIPT_E2E_CATCHUP_WINDOW_SECONDS:-120}"
# #1762 slice 4 gate: net backlog drain rate after the central restart, with
# live flow running. Never lowered to make a run pass.
CATCHUP_MIN_ROWS_PER_SECOND="${RECEIPT_E2E_CATCHUP_MIN_ROWS_PER_SECOND:-50}"
DRAIN_TIMEOUT_SECONDS="${RECEIPT_E2E_DRAIN_TIMEOUT_SECONDS:-300}"
INCIDENT_ROWS="${RECEIPT_E2E_INCIDENT_ROWS:-53000}"
INCIDENT_LIVE_ROWS_PER_SECOND="${RECEIPT_E2E_INCIDENT_LIVE_ROWS_PER_SECOND:-4.5}"

API_PORT="${RECEIPT_E2E_API_PORT:-8094}"
MQTT_PORT="${RECEIPT_E2E_MQTT_PORT:-1894}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
POSTGRES_DB="nexolab"
POSTGRES_USER="nexolab"
POSTGRES_PASSWORD="receipt-acceptance-postgres-$(python3 -c 'import secrets; print(secrets.token_hex(12))')"
ADMIN_USERNAME="nexolab-security-admin"
INGESTION_USERNAME="nexolab-central-ingestion"
INGESTION_CLIENT_ID="nexolab-central-ingestion"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000001"
NODE_ID="edge-01"
OTHER_NODE_ID="edge-02"
NODE_USERNAME="node:${ORGANIZATION_ID}:${NODE_ID}"
NODE_CLIENT_ID="nexolab-${ORGANIZATION_ID}-${NODE_ID}"
OTHER_NODE_USERNAME="node:${ORGANIZATION_ID}:${OTHER_NODE_ID}"
OTHER_NODE_CLIENT_ID="nexolab-${ORGANIZATION_ID}-${OTHER_NODE_ID}"
SUBSCRIBER_USERNAME="receipts:${ORGANIZATION_ID}:${NODE_ID}"
SUBSCRIBER_CLIENT_ID="nexolab-${ORGANIZATION_ID}-${NODE_ID}-receipts"
PUBLISHER_USERNAME="nexolab-central-receipts-e2e"
RECEIPT_TOPIC="nexolab/v1/${ORGANIZATION_ID}/${NODE_ID}/receipts"
MANAGER_ID="42000000-0000-0000-0000-000000000021"
MANAGER_MEMBERSHIP="52000000-0000-0000-0000-000000000021"
MANAGER_SUBJECT="manager-committed-receipt-acceptance"
JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
JWT_ISSUER="https://auth.nexolab.local/committed-receipt-acceptance"
JWT_AUDIENCE="nexolab-committed-receipt-acceptance"

export POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
export NEXOLAB_MQTT_ADMIN_USERNAME="$ADMIN_USERNAME"
export BROKER_CONTROL_INGESTION_USERNAME="$INGESTION_USERNAME"
export BROKER_CONTROL_INGESTION_CLIENT_ID="$INGESTION_CLIENT_ID"
export BROKER_CONTROL_ORGANIZATION_A="$ORGANIZATION_ID"
export BROKER_CONTROL_JWT_SECRET="$JWT_SECRET"
export BROKER_CONTROL_JWT_ISSUER="$JWT_ISSUER"
export BROKER_CONTROL_JWT_AUDIENCE="$JWT_AUDIENCE"
export BROKER_CONTROL_API_PORT="$API_PORT"
export BROKER_CONTROL_MQTT_PORT="$MQTT_PORT"
export BROKER_CONTROL_SECRETS_DIR="$SECRETS_DIR"
export BROKER_CONTROL_POSTGRES_VOLUME="${PROJECT_NAME}-postgres"
export BROKER_CONTROL_MQTT_VOLUME="${PROJECT_NAME}-mqtt"
export BROKER_CONTROL_NETWORK="${PROJECT_NAME}-network"
export BROKER_CONTROL_TELEMETRY_IMAGE="nexolab-telemetry-service:committed-receipt-acceptance"
export BROKER_CONTROL_MQTT_IMAGE="nexolab-mqtt-dynamic-security:committed-receipt-acceptance"
export RECEIPT_E2E_DEVICE_AGENT_IMAGE="nexolab-device-agent:committed-receipt-acceptance"
export RECEIPT_E2E_EDGE_VOLUME="${PROJECT_NAME}-edge"
export RECEIPT_E2E_MOSQUITTO_CONFIG="$PRIVATE_DIR/mosquitto.conf"
export RECEIPT_E2E_PUBLISHER_USERNAME="$PUBLISHER_USERNAME"
export RECEIPT_E2E_SAMPLE_INTERVAL_SECONDS="$LIVE_INTERVAL"
export RECEIPT_E2E_REPLAY_AFTER_SECONDS="$REPLAY_AFTER"

compose() {
  docker compose --project-name "$PROJECT_NAME" \
    -f "$BASE_COMPOSE" -f "$RECEIPT_COMPOSE" "$@"
}

admin() {
  compose exec -T mqtt /usr/local/bin/nexolab-dynsec-admin "$@"
}

log() {
  local line
  line="$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"
  printf '%s\n' "$line" | tee -a "$TIMELINE"
}

fail() {
  log "FAIL: $*"
  echo "Committed-receipt acceptance failed: $*" >&2
  exit 1
}

now() {
  python3 -c 'import time; print(f"{time.monotonic():.3f}")'
}

cleanup() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/compose-ps.log" 2>&1
  compose logs --no-color --timestamps \
    postgres mqtt mqtt-policy-init telemetry-migrate telemetry-service device-agent \
    >"$SERVICE_LOG" 2>&1
  compose down --volumes --remove-orphans >/dev/null 2>&1
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Committed-receipt acceptance failed (exit $status)." >&2
    tail -n 200 "$SERVICE_LOG" >&2
    if [[ ! -f "$EVIDENCE_DIR/summary.md" ]]; then
      printf '%s\n' "## Committed-receipt acceptance (#1762)" "" \
        "**FAILED** before the summary was written. See timeline.log." \
        >"$EVIDENCE_DIR/summary.md"
    fi
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

# ------------------------------------------------------------------ helpers
generate_secret() {
  # Throwaway credential, generated at runtime. $2 is the file mode.
  python3 - "$1" "$2" <<'PY'
from pathlib import Path
import secrets
import sys
path = Path(sys.argv[1])
path.write_text("nxl_e2e_" + secrets.token_urlsafe(32), encoding="utf-8")
path.chmod(int(sys.argv[2], 8))
PY
}

copy_secret() {
  cp "$1" "$2"
  chmod "$3" "$2"
}

generate_encryption_key() {
  python3 - "$1" <<'PY'
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
payload = {
    "iss": issuer, "aud": audience, "sub": subject,
    "email": "manager-receipts@nexolab.local", "name": "Receipt Manager",
    "iat": now, "nbf": now - 5, "exp": now + 3600,
}
unsigned = f"{encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(payload)}"
signature = hmac.new(secret.encode(), unsigned.encode("ascii"), hashlib.sha256).digest()
print(f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}")
PY
}

api_get() {
  curl --fail-with-body --silent --show-error \
    -H "Authorization: Bearer ${MANAGER_TOKEN}" \
    -H "X-Organization-ID: ${ORGANIZATION_ID}" \
    -H "Accept: application/json" \
    "${API_BASE_URL}$1"
}

api_post() {
  curl --fail-with-body --silent --show-error -X POST \
    -H "Authorization: Bearer ${MANAGER_TOKEN}" \
    -H "X-Organization-ID: ${ORGANIZATION_ID}" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -H "Idempotency-Key: $3" \
    --data "$2" "${API_BASE_URL}$1"
}

wait_for_url() {
  for _ in $(seq 1 240); do
    if curl --fail --silent --show-error "$1" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  fail "timed out waiting for $2"
}

wait_for_broker() {
  for _ in $(seq 1 160); do
    if admin list-clients >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  fail "timed out waiting for authenticated broker administration"
}

wait_for_control() {
  for _ in $(seq 1 200); do
    if api_get "/api/v1/nodes/$1/broker-control" \
      | jq -e --arg operation "$2" \
        '.synchronization == "applied" and .latest_command.operation == $operation' \
        >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  fail "timed out waiting for $1 broker operation $2"
}

agent_health() {
  compose exec -T device-agent python - <<'PY'
import json
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=3) as response:
    print(json.dumps(json.load(response), separators=(",", ":")))
PY
}

receipt_metric() {
  # $1: jq path below .committed_receipts
  agent_health | jq -er ".committed_receipts.$1"
}

pending_count() {
  receipt_metric pending_count
}

wait_for_agent() {
  for _ in $(seq 1 240); do
    if agent_health 2>/dev/null \
      | jq -e '.committed_receipts.receipt_subscriber_connected == true
               and .committed_receipts.subscribe_acknowledged == true' >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  fail "Device Agent receipt subscriber did not connect"
}

# Read-only snapshot of the Edge outbox in one SQLite read transaction.
edge_state() {
  compose exec -T device-agent python - <<'PY'
import json
import sqlite3
connection = sqlite3.connect("/var/lib/nexolab/edge.db", timeout=10, isolation_level=None)
connection.execute("BEGIN")
row = connection.execute(
    "SELECT last_sequence FROM node_stream_sequences WHERE stream = 'telemetry'"
).fetchone()
pending = []
for record_id, event_id, payload in connection.execute(
    "SELECT id, event_id, payload FROM outbound_queue ORDER BY id"
):
    body = json.loads(payload)
    pending.append({"id": record_id, "event_id": event_id, "node_sequence": body["node_sequence"]})
try:
    ledger = connection.execute("SELECT count(*) FROM committed_receipt_ledger").fetchone()[0]
except sqlite3.OperationalError:
    ledger = 0
connection.execute("COMMIT")
print(json.dumps({
    "last_sequence": int(row[0]) if row else 0,
    "pending": pending,
    "ledger_rows": ledger,
}, separators=(",", ":")))
PY
}

psql_value() {
  compose exec -T postgres psql -At -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"
}

pg_node_rows() {
  psql_value "SELECT count(*) FROM telemetry_samples WHERE node_id = '${NODE_ID}';"
}

pg_export_node_rows() {
  # event_id,node_sequence for every PostgreSQL row of the node.
  compose exec -T postgres psql -At -F, -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "SELECT event_id, (raw_payload->>'node_sequence')::bigint FROM telemetry_samples WHERE node_id = '${NODE_ID}' ORDER BY 2, 1;" \
    >"$1"
}

mqtt_publish_as() {
  # username password client-id topic payload; QoS 1, MQTT 3.1.1, never retained.
  compose exec -T mqtt mosquitto_pub \
    -h 127.0.0.1 -p 1883 -V mqttv311 -q 1 --quiet \
    -u "$1" -P "$2" -i "$3" -t "$4" -m "$5" \
    >>"$EVIDENCE_DIR/forged-publish.log" 2>&1 || true
}

receipt_payload() {
  # event_id node_sequence node_id [receipt_id]
  python3 - "$ORGANIZATION_ID" "$1" "$2" "$3" "${4:-}" <<'PY'
import json
import sys
import uuid
from datetime import datetime, timezone
organization, event_id, sequence, node, receipt_id = sys.argv[1:]
print(json.dumps({
    "contract_version": 1,
    "receipt_id": receipt_id or str(uuid.uuid4()),
    "event_id": event_id,
    "organization_id": organization,
    "node_id": node,
    "stream": "telemetry",
    "node_sequence": int(sequence),
    "receipt_level": "postgres_committed",
    "accepted_at": datetime.now(timezone.utc).isoformat(),
}, separators=(",", ":")))
PY
}

# ------------------------------------------------------------------- setup
rm -rf "$EVIDENCE_DIR" "$PRIVATE_DIR"
mkdir -p "$EVIDENCE_DIR" "$SECRETS_DIR"
chmod 0755 "$PRIVATE_DIR" "$SECRETS_DIR"
: >"$TIMELINE"

generate_secret "$SECRETS_DIR/admin-password" 0444
generate_secret "$SECRETS_DIR/ingestion-password" 0444
generate_encryption_key "$SECRETS_DIR/broker-control-key"
# Provisioning copies are 0600 (the admin tool refuses anything broader); the
# runtime copies are readable by the non-root service users of this fixture.
generate_secret "$SECRETS_DIR/receipt-publisher-password.provision" 0600
copy_secret "$SECRETS_DIR/receipt-publisher-password.provision" \
  "$SECRETS_DIR/receipt-publisher-password" 0444
generate_secret "$SECRETS_DIR/edge-01-receipt-password.provision" 0600
copy_secret "$SECRETS_DIR/edge-01-receipt-password.provision" \
  "$SECRETS_DIR/edge-01-receipt-password" 0444
generate_secret "$SECRETS_DIR/edge-02-password" 0600

# Production broker config with a deliberately tiny per-client queue.
grep -Eq '^max_queued_messages [0-9]+$' "$BROKER_CONFIG_SOURCE" \
  || fail "broker config has no max_queued_messages line"
sed -E "s/^max_queued_messages [0-9]+$/max_queued_messages ${QUEUE_CAP}/" \
  "$BROKER_CONFIG_SOURCE" >"$RECEIPT_E2E_MOSQUITTO_CONFIG"
chmod 0644 "$RECEIPT_E2E_MOSQUITTO_CONFIG"
grep -Fx "max_queued_messages ${QUEUE_CAP}" "$RECEIPT_E2E_MOSQUITTO_CONFIG" >/dev/null \
  || fail "tiny broker queue was not configured"
cp "$RECEIPT_E2E_MOSQUITTO_CONFIG" "$EVIDENCE_DIR/mosquitto.acceptance.conf"

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose config --quiet
log "building images"
BUILD_STARTED="$(now)"
compose build mqtt telemetry-service device-agent
BUILD_SECONDS="$(python3 -c "print(round($(now) - $BUILD_STARTED, 1))")"

log "starting PostgreSQL and the Dynamic Security broker"
compose up -d postgres mqtt
wait_for_broker
admin bootstrap-defaults
# The two dedicated receipt identities (#1762 slice 3), provisioned with the
# same admin commands an owner uses on site.
admin create-org-receipt-publisher "$PUBLISHER_USERNAME" "$PUBLISHER_USERNAME" \
  "$ORGANIZATION_ID" /run/secrets/nexolab/receipt-publisher-password.provision
admin create-node-receipt-subscriber "$SUBSCRIBER_USERNAME" "$SUBSCRIBER_CLIENT_ID" \
  "$ORGANIZATION_ID" "$NODE_ID" /run/secrets/nexolab/edge-01-receipt-password.provision
# A second node identity of the same organization (never a receipt publisher).
admin create-node "$OTHER_NODE_USERNAME" "$OTHER_NODE_CLIENT_ID" \
  "$ORGANIZATION_ID" "$OTHER_NODE_ID" /run/secrets/nexolab/edge-02-password
admin get-client "$PUBLISHER_USERNAME" >"$EVIDENCE_DIR/publisher-client.txt"
admin get-client "$SUBSCRIBER_USERNAME" >"$EVIDENCE_DIR/subscriber-client.txt"

log "starting telemetry-service with NEXOLAB_COMMITTED_RECEIPTS=enabled"
compose up -d mqtt-policy-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "telemetry service readiness"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" >/dev/null <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES ('$ORGANIZATION_ID', 'committed-receipt-acceptance', 'Committed Receipt Acceptance', true)
ON CONFLICT (id) DO UPDATE SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;
INSERT INTO security_identities (id, provider, subject, email, display_name, is_active, last_authenticated_at)
VALUES ('$MANAGER_ID', 'broker-control-acceptance', '$MANAGER_SUBJECT',
        'manager-receipts@nexolab.local', 'Receipt Manager', true, now())
ON CONFLICT (provider, subject) DO UPDATE SET is_active = true, last_authenticated_at = EXCLUDED.last_authenticated_at;
INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES ('$MANAGER_MEMBERSHIP', '$ORGANIZATION_ID', '$MANAGER_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;
INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES ('$MANAGER_MEMBERSHIP', 'laboratory_manager', 'committed-receipt-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL
compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  <"$ROOT_DIR/scripts/security-acceptance-role-permissions.sql" >/dev/null

MANAGER_TOKEN="$(jwt_token)"
PROVISION_RESPONSE="$(api_post '/api/v1/nodes' \
  "{\"node_id\":\"${NODE_ID}\",\"display_name\":\"Receipt ${NODE_ID}\",\"clock_warning_ms\":30000,\"clock_critical_ms\":120000}" \
  "receipt-provision-${NODE_ID}")"
printf '%s' "$PROVISION_RESPONSE" | jq -er '.provisioning_secret' >"$SECRETS_DIR/edge-01-password"
chmod 0444 "$SECRETS_DIR/edge-01-password"
unset PROVISION_RESPONSE
wait_for_control "$NODE_ID" provision
api_post "/api/v1/nodes/${NODE_ID}/activate" '{"reason":"committed receipt acceptance"}' \
  "receipt-activate-${NODE_ID}" >/dev/null

curl --fail --silent --show-error "$API_BASE_URL/health/ready" \
  | jq '.committed_receipts' >"$EVIDENCE_DIR/central-readiness-initial.json" \
  || fail "central readiness has no committed_receipts section"

# ------------------------------------------------------------ steady flow
log "phase 1: steady flow (sample interval ${LIVE_INTERVAL}s)"
compose up -d --no-deps device-agent
wait_for_agent
applied=0
steady_pending=-1
for _ in $(seq 1 240); do
  applied="$(receipt_metric receipts_applied_total 2>/dev/null || echo 0)"
  steady_pending="$(pending_count 2>/dev/null || echo -1)"
  if (( applied >= STEADY_MIN_ROWS && steady_pending >= 0 && steady_pending <= STEADY_MAX_PENDING )); then
    break
  fi
  sleep 0.5
done
(( applied >= STEADY_MIN_ROWS )) || fail "steady flow applied only ${applied} receipts"
# Live flow keeps a few rows in flight (one publisher idle period at most).
(( steady_pending >= 0 && steady_pending <= STEADY_MAX_PENDING )) \
  || fail "steady flow Edge outbox is not bounded (pending=${steady_pending})"
agent_health >"$EVIDENCE_DIR/edge-health-steady.json"
STEADY_PG_ROWS="$(pg_node_rows)"
log "steady: receipts_applied=${applied} postgres_rows=${STEADY_PG_ROWS} edge_pending=${steady_pending}"
# A real receipt that the Edge already applied, kept for the duplicate check.
DUPLICATE_RECEIPT="$(psql_value "SELECT payload::text FROM telemetry_committed_receipts WHERE node_id = '${NODE_ID}' AND published_at IS NOT NULL ORDER BY node_sequence LIMIT 1;")"
[[ -n "$DUPLICATE_RECEIPT" ]] || fail "no published receipt available for the duplicate check"

# ---------------------------------------------------------- central outage
log "phase 2: central ingestion outage (broker queue cap ${QUEUE_CAP}, sample interval ${OUTAGE_INTERVAL}s)"
OUTAGE_STARTED="$(now)"
compose stop telemetry-service
# Fast simulated sampling builds the backlog that the catch-up gate measures.
export RECEIPT_E2E_SAMPLE_INTERVAL_SECONDS="$OUTAGE_INTERVAL"
compose up -d --no-deps device-agent
wait_for_agent
for _ in $(seq 1 600); do
  if (( $(pending_count 2>/dev/null || echo 0) >= OUTAGE_MIN_PENDING )); then
    break
  fi
  sleep 0.5
done
OUTAGE_PENDING="$(pending_count)"
(( OUTAGE_PENDING >= OUTAGE_MIN_PENDING )) \
  || fail "outage reached only ${OUTAGE_PENDING} pending rows"
# Drop-after-PUBACK evidence: the broker discarded messages for the offline
# central consumer because its queue was full (the 2026-11-25 loss class).
DROP_LINE="Outgoing messages are being dropped for client ${INGESTION_CLIENT_ID}"
for _ in $(seq 1 20); do
  if compose logs --no-color mqtt 2>&1 | grep -Fq "$DROP_LINE"; then
    break
  fi
  sleep 0.5
done
compose logs --no-color mqtt 2>&1 | grep -F "$DROP_LINE" >"$EVIDENCE_DIR/broker-queue-overflow.log" \
  || fail "broker did not report a queue overflow for ${INGESTION_CLIENT_ID}"
FIRST_TRANSMISSIONS="$(receipt_metric first_transmissions_total)"
log "outage: edge_pending=${OUTAGE_PENDING} first_transmissions(PUBACK)=${FIRST_TRANSMISSIONS} broker_overflow=observed"

edge_state >"$EVIDENCE_DIR/edge-outage-snapshot.json"
jq -e '.pending | length > 1' "$EVIDENCE_DIR/edge-outage-snapshot.json" >/dev/null \
  || fail "outage snapshot has fewer than two pending rows"
# Target row for the forged/invalid receipt checks: the oldest pending row
# that is NOT in PostgreSQL. A row committed just before the outage can still
# await its receipt, so the head alone would make the check racy or vacuous.
# With exact-row binding a valid receipt could prune ANY pending row, so the
# checks must target a row whose loss the accounting would detect.
CANDIDATES="$(jq -r '[.pending[:100][] | .event_id] | map("'"'"'" + . + "'"'"'") | join(",")' \
  "$EVIDENCE_DIR/edge-outage-snapshot.json")"
psql_value "SELECT event_id FROM telemetry_samples WHERE event_id IN (${CANDIDATES});" \
  >"$EVIDENCE_DIR/outage-candidates-in-postgres.txt"
TARGET_INDEX="$(python3 - "$EVIDENCE_DIR/edge-outage-snapshot.json" \
  "$EVIDENCE_DIR/outage-candidates-in-postgres.txt" <<'PY'
import json
import sys
pending = json.load(open(sys.argv[1], encoding="utf-8"))["pending"]
committed = {line.strip() for line in open(sys.argv[2], encoding="utf-8") if line.strip()}
for index, row in enumerate(pending[:99]):
    if row["event_id"] not in committed:
        print(index)
        break
else:
    print(-1)
PY
)"
(( TARGET_INDEX >= 0 )) \
  || fail "no pending outage row is absent from PostgreSQL; forged-receipt check would be vacuous"
HEAD_ID="$(jq -r ".pending[${TARGET_INDEX}].id" "$EVIDENCE_DIR/edge-outage-snapshot.json")"
HEAD_EVENT="$(jq -r ".pending[${TARGET_INDEX}].event_id" "$EVIDENCE_DIR/edge-outage-snapshot.json")"
HEAD_SEQUENCE="$(jq -r ".pending[${TARGET_INDEX}].node_sequence" "$EVIDENCE_DIR/edge-outage-snapshot.json")"
SECOND_ID="$(jq -r ".pending[$((TARGET_INDEX + 1))].id" "$EVIDENCE_DIR/edge-outage-snapshot.json")"
SECOND_EVENT="$(jq -r ".pending[$((TARGET_INDEX + 1))].event_id" "$EVIDENCE_DIR/edge-outage-snapshot.json")"
[[ "$(psql_value "SELECT count(*) FROM telemetry_samples WHERE event_id = '${HEAD_EVENT}';")" == "0" ]] \
  || fail "target outage row is already in PostgreSQL; forged-receipt check would be vacuous"
log "invalid-receipt target: pending index ${TARGET_INDEX}, sequence ${HEAD_SEQUENCE}"

# ------------------------------------------------- forged and invalid receipts
log "phase 3: forged, wrong-node, wrong-sequence, unknown-row and duplicate receipts"
APPLIED_BEFORE="$(receipt_metric receipts_applied_total)"
REJECTED_BEFORE="$(receipt_metric receipts_rejected_total)"
VALID_LOOKING="$(receipt_payload "$HEAD_EVENT" "$HEAD_SEQUENCE" "$NODE_ID")"
: >"$EVIDENCE_DIR/forged-publish.log"
# A receipt that WOULD prune the target row if the broker delivered it,
# published by identities that are not the central receipt publisher. The ACL
# must drop it.
mqtt_publish_as "$OTHER_NODE_USERNAME" "$(tr -d '\r\n' <"$SECRETS_DIR/edge-02-password")" \
  "$OTHER_NODE_CLIENT_ID" "$RECEIPT_TOPIC" "$VALID_LOOKING"
mqtt_publish_as "$SUBSCRIBER_USERNAME" \
  "$(tr -d '\r\n' <"$SECRETS_DIR/edge-01-receipt-password")" \
  "$SUBSCRIBER_CLIENT_ID" "$RECEIPT_TOPIC" "$(receipt_payload "$HEAD_EVENT" "$HEAD_SEQUENCE" "$NODE_ID")"
mqtt_publish_as "$NODE_USERNAME" "$(tr -d '\r\n' <"$SECRETS_DIR/edge-01-password")" \
  "$NODE_CLIENT_ID" "$RECEIPT_TOPIC" "$(receipt_payload "$HEAD_EVENT" "$HEAD_SEQUENCE" "$NODE_ID")"
sleep 3
wait_for_agent
[[ "$(receipt_metric receipts_applied_total)" == "$APPLIED_BEFORE" ]] \
  || fail "a forged receipt from a non-publisher identity was applied"
[[ "$(receipt_metric receipts_rejected_total)" == "$REJECTED_BEFORE" ]] \
  || fail "a forged receipt from a non-publisher identity was delivered to the Edge"

# The central publisher identity (its runtime is stopped, so its client id is
# free) sends receipts the Edge contract must reject without pruning. Since
# slice 4 a receipt may name any pending row, but only with that exact row's
# identity: a wrong node, another row's sequence, an unknown (or already
# pruned) row and a replayed receipt_id are all rejected.
PUBLISHER_PASSWORD="$(tr -d '\r\n' <"$SECRETS_DIR/receipt-publisher-password")"
UNKNOWN_EVENT="$(python3 -c 'import uuid; print(uuid.uuid4())')"
mqtt_publish_as "$PUBLISHER_USERNAME" "$PUBLISHER_PASSWORD" "$PUBLISHER_USERNAME" \
  "$RECEIPT_TOPIC" "$(receipt_payload "$HEAD_EVENT" "$HEAD_SEQUENCE" "$OTHER_NODE_ID")"
mqtt_publish_as "$PUBLISHER_USERNAME" "$PUBLISHER_PASSWORD" "$PUBLISHER_USERNAME" \
  "$RECEIPT_TOPIC" "$(receipt_payload "$SECOND_EVENT" "$HEAD_SEQUENCE" "$NODE_ID")"
mqtt_publish_as "$PUBLISHER_USERNAME" "$PUBLISHER_PASSWORD" "$PUBLISHER_USERNAME" \
  "$RECEIPT_TOPIC" "$(receipt_payload "$UNKNOWN_EVENT" "$HEAD_SEQUENCE" "$NODE_ID")"
mqtt_publish_as "$PUBLISHER_USERNAME" "$PUBLISHER_PASSWORD" "$PUBLISHER_USERNAME" \
  "$RECEIPT_TOPIC" "$DUPLICATE_RECEIPT"
EXPECTED_REJECTED=$((REJECTED_BEFORE + 4))
for _ in $(seq 1 60); do
  if (( $(receipt_metric receipts_rejected_total) >= EXPECTED_REJECTED )); then
    break
  fi
  sleep 0.25
done
agent_health >"$EVIDENCE_DIR/edge-health-after-invalid-receipts.json"
jq -e --argjson expected "$EXPECTED_REJECTED" --argjson applied "$APPLIED_BEFORE" '
  .committed_receipts.receipts_rejected_total == $expected
  and .committed_receipts.receipts_applied_total == $applied
  and (.committed_receipts.receipts_rejected_by_reason.receipt_identity_mismatch // 0) >= 1
  and (.committed_receipts.receipts_rejected_by_reason.receipt_sequence_mismatch // 0) >= 1
  and (.committed_receipts.receipts_rejected_by_reason.no_matching_pending_telemetry // 0) >= 1
  and (.committed_receipts.receipts_rejected_by_reason.receipt_id_already_processed // 0) >= 1
' "$EVIDENCE_DIR/edge-health-after-invalid-receipts.json" >/dev/null \
  || fail "wrong-node, wrong-sequence, unknown-row or duplicate receipt was not rejected exactly as expected"
edge_state >"$EVIDENCE_DIR/edge-after-invalid-receipts.json"
jq -e --argjson target "$HEAD_ID" --argjson second "$SECOND_ID" \
  '([.pending[].id] | index($target)) != null and ([.pending[].id] | index($second)) != null' \
  "$EVIDENCE_DIR/edge-after-invalid-receipts.json" >/dev/null \
  || fail "an invalid receipt pruned the target or second Edge outbox row"
[[ "$(jq -r '.pending | length' "$EVIDENCE_DIR/edge-after-invalid-receipts.json")" -ge \
   "$(jq -r '.pending | length' "$EVIDENCE_DIR/edge-outage-snapshot.json")" ]] \
  || fail "an invalid receipt pruned an Edge outbox row"
log "invalid receipts: forged=not_delivered wrong_node/wrong_sequence/unknown_row/duplicate=rejected target=retained"

# -------------------------------------------- Edge restart during the outage
log "phase 4: Edge restart during the outage; live interval -> ${RECOVERY_INTERVAL}s"
export RECEIPT_E2E_SAMPLE_INTERVAL_SECONDS="$RECOVERY_INTERVAL"
compose up -d --no-deps device-agent
wait_for_agent
PENDING_AFTER_EDGE_RESTART="$(pending_count)"
(( PENDING_AFTER_EDGE_RESTART >= OUTAGE_PENDING )) \
  || fail "Edge restart lost rows (${OUTAGE_PENDING} -> ${PENDING_AFTER_EDGE_RESTART})"
# Let the first (re)transmission after the restart reach the broker, so every
# pending row is replay-eligible once central is back.
for _ in $(seq 1 120); do
  if (( $(receipt_metric first_transmissions_total) >= PENDING_AFTER_EDGE_RESTART )); then
    break
  fi
  sleep 0.5
done
sleep "$REPLAY_AFTER"
OUTAGE_SECONDS="$(python3 -c "print(round($(now) - $OUTAGE_STARTED, 1))")"

# ------------------------------------------------------- central restart
log "phase 5: central restart, bounded bulk catch-up with live flow (${RECOVERY_INTERVAL}s)"
P0="$(pending_count)"
PG0="$(pg_node_rows)"
REPLAY_PUBACKS0="$(receipt_metric replay_pubacks_total)"
RESTART_AT="$(now)"
compose start telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "telemetry service readiness after restart"
# Catch-up measurement window: from central readiness until half of the
# backlog present at readiness is gone (net of live rows), or the timeout.
CATCHUP_START="$(now)"
PC0="$(pending_count)"
PGC0="$(pg_node_rows)"
SEQ_C0="$(edge_state | jq -r '.last_sequence')"
CATCHUP_SAMPLES="$EVIDENCE_DIR/catch-up-samples.csv"
printf 'seconds,edge_pending,postgres_rows\n' >"$CATCHUP_SAMPLES"
printf '0,%s,%s\n' "$PC0" "$PGC0" >>"$CATCHUP_SAMPLES"
while :; do
  sleep 0.5
  # Read the Edge first: the elapsed time is taken after both reads, so the
  # measured rate can only be understated, never overstated.
  pending="$(pending_count)"
  pg_rows="$(pg_node_rows)"
  elapsed="$(python3 -c "print(round($(now) - $CATCHUP_START, 3))")"
  printf '%s,%s,%s\n' "$elapsed" "$pending" "$pg_rows" >>"$CATCHUP_SAMPLES"
  if python3 -c "import sys; sys.exit(0 if ($elapsed >= $CATCHUP_WINDOW_SECONDS or $pending * 2 <= $PC0) else 1)"; then
    break
  fi
done
CATCHUP_SECONDS="$elapsed"
PC1="$pending"
PGC1="$pg_rows"
EDGE_RESTART2_AT="$(now)"
P1="$(pending_count)"
PG1="$(pg_node_rows)"
SEQ_C1="$(edge_state | jq -r '.last_sequence')"
REPLAY_PUBACKS1="$(receipt_metric replay_pubacks_total)"
agent_health >"$EVIDENCE_DIR/edge-health-before-mid-replay-restart.json"
LEDGER1="$(edge_state | jq -r '.ledger_rows')"
(( P1 > 0 )) || fail "catch-up finished before the mid-replay Edge restart; scenario not exercised"
(( SEQ_C1 > SEQ_C0 )) || fail "live flow stopped during catch-up (last_sequence ${SEQ_C0} -> ${SEQ_C1})"

# ---------------------------------------------- Edge restart mid-replay
log "phase 6: Edge restart mid-replay (pending=${P1})"
compose restart device-agent
wait_for_agent
P1_AFTER="$(pending_count)"
LEDGER1_AFTER="$(edge_state | jq -r '.ledger_rows')"
(( P1_AFTER > 0 )) || fail "Edge restart mid-replay lost the pending rows"
(( LEDGER1_AFTER >= LEDGER1 )) || fail "Edge receipt ledger was not durable across restart"
EDGE_BACK_AT="$(now)"

# ------------------------------------------------------- drain to zero
log "phase 7: drain to zero"
DRAINED=""
for _ in $(seq 1 "$DRAIN_TIMEOUT_SECONDS"); do
  state="$(edge_state)"
  if [[ "$(printf '%s' "$state" | jq -r '.pending | length')" == "0" ]]; then
    DRAINED="$state"
    break
  fi
  sleep 1
done
[[ -n "$DRAINED" ]] || fail "Edge outbox did not drain to zero within ${DRAIN_TIMEOUT_SECONDS}s"
DRAINED_AT="$(now)"
printf '%s\n' "$DRAINED" >"$EVIDENCE_DIR/edge-final-state.json"
LAST_SEQUENCE="$(jq -r '.last_sequence' "$EVIDENCE_DIR/edge-final-state.json")"
PG2="$(pg_node_rows)"
agent_health >"$EVIDENCE_DIR/edge-health-final.json"
[[ "$(jq -r '.committed_receipts.pending_count' "$EVIDENCE_DIR/edge-health-final.json")" =~ ^[01]$ ]] \
  || fail "Edge health does not report a drained outbox"
curl --fail --silent --show-error "$API_BASE_URL/metrics/json" \
  | jq '.committed_receipts // .' >"$EVIDENCE_DIR/central-metrics-final.json" || true
curl --fail --silent --show-error "$API_BASE_URL/health/ready" \
  | jq '.committed_receipts' >"$EVIDENCE_DIR/central-readiness-final.json" || true
log "drained: last_sequence=${LAST_SEQUENCE} postgres_rows=${PG2}"

# -------------------------------------------------- exact accounting
pg_export_node_rows "$EVIDENCE_DIR/postgres-rows.csv"
if ! python3 - "$EVIDENCE_DIR/postgres-rows.csv" "$LAST_SEQUENCE" \
  "$EVIDENCE_DIR/edge-outage-snapshot.json" "$HEAD_EVENT" \
  >"$EVIDENCE_DIR/accounting.json" <<'PY'
import collections
import json
import sys
rows_path, last_sequence, snapshot_path, head_event = sys.argv[1:]
last_sequence = int(last_sequence)
rows = []
with open(rows_path, encoding="utf-8") as handle:
    for line in handle:
        line = line.strip()
        if line:
            event_id, sequence = line.split(",")
            rows.append((event_id, int(sequence)))
events = collections.Counter(event for event, _ in rows)
sequences = collections.Counter(sequence for _, sequence in rows)
by_event = dict(rows)
duplicate_events = sorted(e for e, n in events.items() if n > 1)
duplicate_sequences = sorted(s for s, n in sequences.items() if n > 1)
expected = set(range(1, last_sequence + 1))
present = {s for s in sequences if s <= last_sequence}
missing = sorted(expected - present)
snapshot = json.load(open(snapshot_path, encoding="utf-8"))["pending"]
outage_missing = [
    item["event_id"] for item in snapshot
    if by_event.get(item["event_id"]) != item["node_sequence"]
]
result = {
    "postgres_rows": len(rows),
    "edge_last_sequence": last_sequence,
    "duplicate_event_ids": len(duplicate_events),
    "duplicate_node_sequences": len(duplicate_sequences),
    "missing_sequences": missing[:50],
    "missing_sequence_count": len(missing),
    "outage_rows_checked": len(snapshot),
    "outage_rows_missing_or_rebound": len(outage_missing),
    "forged_head_event_committed_once": events.get(head_event, 0) == 1,
}
print(json.dumps(result, indent=2, sort_keys=True))
ok = (
    not duplicate_events and not duplicate_sequences and not missing
    and not outage_missing and result["forged_head_event_committed_once"]
    and last_sequence > 0
)
sys.exit(0 if ok else 1)
PY
then
  fail "PostgreSQL accounting failed: $(cat "$EVIDENCE_DIR/accounting.json")"
fi
log "accounting: every event 1..${LAST_SEQUENCE} in PostgreSQL exactly once"

# ------------------------------------------------------- throughput summary
# The summary is written before the throughput gate is enforced, so a failing
# run still shows its numbers. Correctness assertions above already passed.
GATE_STATUS=0
python3 - "$EVIDENCE_DIR/summary.json" "$EVIDENCE_DIR/summary.md" <<PY || GATE_STATUS=$?
import json
import sys

def rate(rows, seconds):
    return round(rows / seconds, 3) if seconds > 0 else None

restart_at = $RESTART_AT
catchup_start = $CATCHUP_START
mid_restart_at = $EDGE_RESTART2_AT
edge_back_at = $EDGE_BACK_AT
drained_at = $DRAINED_AT
catchup_seconds = float($CATCHUP_SECONDS)
pc0, pc1 = $PC0, $PC1
pgc0, pgc1 = $PGC0, $PGC1
seq_c0, seq_c1 = $SEQ_C0, $SEQ_C1
bulk_window = drained_at - edge_back_at
total_window = drained_at - restart_at
pg0, pg1, pg2 = $PG0, $PG1, $PG2
p0, p1, p1_after = $P0, $P1, $P1_AFTER
replay_pubacks = $REPLAY_PUBACKS1 - $REPLAY_PUBACKS0
live_rows = seq_c1 - seq_c0
net_rate = rate(pc0 - pc1, catchup_seconds)
commit_rate = rate(pgc1 - pgc0, catchup_seconds)
gate = float($CATCHUP_MIN_ROWS_PER_SECOND)
gate_passed = bool(net_rate is not None and net_rate >= gate)
incident_rows = $INCIDENT_ROWS
incident_live = $INCIDENT_LIVE_ROWS_PER_SECOND
catch_up_metrics = json.load(open("$EVIDENCE_DIR/edge-health-before-mid-replay-restart.json", encoding="utf-8"))
catch_up_metrics = catch_up_metrics.get("committed_receipts", {}).get("catch_up", {})
summary = {
    "issue": 1762,
    "result": "PASS" if gate_passed else "FAIL_THROUGHPUT_GATE",
    "parameters": {
        "broker_max_queued_messages": $QUEUE_CAP,
        "steady_sample_interval_seconds": $LIVE_INTERVAL,
        "outage_sample_interval_seconds": $OUTAGE_INTERVAL,
        "live_sample_interval_during_catch_up_seconds": $RECOVERY_INTERVAL,
        "edge_replay_after_seconds": $REPLAY_AFTER,
        "edge_catch_up_window": catch_up_metrics.get("window"),
        "edge_catch_up_max_rows_per_second": catch_up_metrics.get("max_rows_per_second"),
        "catch_up_gate_rows_per_second": gate,
        "image_build_seconds": $BUILD_SECONDS,
    },
    "outage": {
        "seconds": $OUTAGE_SECONDS,
        "edge_pending_at_outage_snapshot": $OUTAGE_PENDING,
        "broker_queue_overflow_observed": True,
        "forged_receipts_from_non_publishers": "not_delivered",
        "wrong_node_wrong_sequence_unknown_row_duplicate_receipts": "rejected_no_prune",
        "edge_restart_during_outage_rows_retained": $PENDING_AFTER_EDGE_RESTART,
    },
    "recovery": {
        "edge_pending_at_central_restart": p0,
        "central_restart_to_ready_seconds": round(catchup_start - restart_at, 1),
        "catch_up_window_seconds": round(catchup_seconds, 1),
        "catch_up_edge_pending_start": pc0,
        "catch_up_edge_pending_end": pc1,
        "catch_up_net_backlog_rows_per_second": net_rate,
        "catch_up_postgres_rows_committed": pgc1 - pgc0,
        "catch_up_postgres_commit_rows_per_second": commit_rate,
        "catch_up_live_rows_generated": live_rows,
        "catch_up_gate_passed": gate_passed,
        "catch_up_resent_rows_since_restart": replay_pubacks,
        "edge_catch_up_metrics": catch_up_metrics,
        "edge_pending_before_mid_replay_restart": p1,
        "edge_pending_after_mid_replay_restart": p1_after,
        "post_restart_drain_seconds": round(bulk_window, 1),
        "post_restart_rows_per_second": rate(p1_after, bulk_window),
        "total_recovery_seconds": round(total_window, 1),
        "total_rows_committed_during_recovery": pg2 - pg0,
        "total_recovery_rows_per_second": rate(pg2 - pg0, total_window),
    },
    "accounting": json.load(open("$EVIDENCE_DIR/accounting.json", encoding="utf-8")),
    "extrapolation_2026_11_25": {
        "rows": incident_rows,
        "minutes_at_net_catch_up_rate_with_live_flow": (
            round(incident_rows / net_rate / 60, 1) if net_rate else None
        ),
        "site_live_rows_per_second": incident_live,
        "converges_with_site_live_flow": bool(net_rate and net_rate > 0),
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(summary, handle, indent=2, sort_keys=True)
r = summary["recovery"]
x = summary["extrapolation_2026_11_25"]
a = summary["accounting"]
verdict = (
    "**PASS**: every generated event is in PostgreSQL exactly once, the Edge outbox drained to zero "
    f"and the catch-up reached {net_rate} rows/s (gate {gate:g} rows/s)."
    if gate_passed
    else f"**FAIL (throughput gate)**: correctness passed, but the catch-up reached {net_rate} rows/s, "
    f"below the {gate:g} rows/s gate."
)
lines = [
    "## Committed-receipt end-to-end acceptance (#1762 slices 3-4)",
    "",
    verdict,
    "",
    "| Check | Result |",
    "| --- | --- |",
    f"| Broker queue cap / overflow (drop after PUBACK) | {$QUEUE_CAP} messages / observed |",
    f"| Edge rows pending at the outage snapshot | {$OUTAGE_PENDING} |",
    "| Forged receipts from non-publisher identities | not delivered (ACL) |",
    "| Wrong-node, wrong-sequence, unknown-row and duplicate receipts | rejected, no prune |",
    f"| Edge restart during outage | {$PENDING_AFTER_EDGE_RESTART} rows retained |",
    f"| Edge restart mid-catch-up | {p1} -> {p1_after} rows retained |",
    f"| PostgreSQL rows 1..{a['edge_last_sequence']} | {a['postgres_rows']} rows, 0 duplicates, {a['missing_sequence_count']} missing |",
    "",
    "### Measured recovery throughput",
    "",
    "| Phase | Seconds | Rows | Rows/s |",
    "| --- | --- | --- | --- |",
    f"| Catch-up after central restart, net backlog drain with live flow (gate {gate:g}) | {r['catch_up_window_seconds']} | {pc0 - pc1} | {net_rate} |",
    f"| Catch-up after central restart, PostgreSQL commits (backlog + live) | {r['catch_up_window_seconds']} | {r['catch_up_postgres_rows_committed']} | {commit_rate} |",
    f"| After the mid-catch-up Edge restart (all retained rows resent once) | {r['post_restart_drain_seconds']} | {p1_after} | {r['post_restart_rows_per_second']} |",
    f"| Whole recovery (central restart to empty outbox) | {r['total_recovery_seconds']} | {r['total_rows_committed_during_recovery']} | {r['total_recovery_rows_per_second']} |",
    "",
    f"Live flow kept running during catch-up: {live_rows} new rows at a {$RECOVERY_INTERVAL} s sample interval. "
    f"Central restart to readiness took {r['central_restart_to_ready_seconds']} s and is not in the catch-up window.",
    "",
    f"At the net catch-up rate, {x['rows']} rows (2026-11-25 scale) drain in about "
    f"**{x['minutes_at_net_catch_up_rate_with_live_flow']} min** while live flow continues.",
    "",
    "Before slice 4 (head replay, one row per receipt round trip): about 1.1 rows/s head replay, "
    "2.3 rows/s overall (slice 3 acceptance, 2026-11-25).",
    "",
    f"Edge catch-up window {catch_up_metrics.get('window')} rows, rate cap {catch_up_metrics.get('max_rows_per_second')} rows/s, "
    f"replay-after {$REPLAY_AFTER} s (default 60 s, shortened to bound the job).",
    "Synthetic CI fixture only: hardware, site broker ACL and site recovery remain UNVERIFIED.",
]
with open(sys.argv[2], "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")
sys.exit(0 if gate_passed else 3)
PY
cat "$EVIDENCE_DIR/summary.md"
if (( GATE_STATUS != 0 )); then
  fail "catch-up throughput gate failed (see summary.md); correctness assertions passed"
fi
log "committed-receipt end-to-end acceptance PASSED"
