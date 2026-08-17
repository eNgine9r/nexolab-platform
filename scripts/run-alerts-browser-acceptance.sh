#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
PROJECT_NAME="nexolab-alerts-acceptance"
API_PORT="${NEXOLAB_ALERTS_API_PORT:-8083}"
MQTT_PORT="${NEXOLAB_ALERTS_MQTT_PORT:-1885}"
FRONTEND_PORT="${NEXOLAB_ALERTS_FRONTEND_PORT:-3103}"
OBJECT_STORAGE_PORT="${NEXOLAB_ALERTS_OBJECT_STORAGE_PORT:-9012}"
OBJECT_STORAGE_CONSOLE_PORT="${NEXOLAB_ALERTS_OBJECT_STORAGE_CONSOLE_PORT:-9013}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/ws"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"
FRONTEND_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-frontend.log"
SERVICE_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-services.log"
FRONTEND_PID=""

POSTGRES_PASSWORD="alerts-acceptance-postgres"
MINIO_ROOT_USER="alerts-acceptance-minio"
MINIO_ROOT_PASSWORD="alerts-acceptance-minio-secret"
JWT_SECRET="alerts-browser-acceptance-secret-with-at-least-thirty-two-bytes"
JWT_ISSUER="https://auth.nexolab.local/alerts-acceptance"
JWT_AUDIENCE="nexolab-alerts-acceptance"
JWT_PROVIDER="alerts-acceptance"

ORGANIZATION_A="00000000-0000-0000-0000-000000000001"
ORGANIZATION_B="00000000-0000-0000-0000-000000000002"
MANAGER_A_ID="20000000-0000-0000-0000-000000000001"
MANAGER_B_ID="20000000-0000-0000-0000-000000000002"
VIEWER_A_ID="20000000-0000-0000-0000-000000000003"
MANAGER_A_MEMBERSHIP="30000000-0000-0000-0000-000000000001"
MANAGER_B_MEMBERSHIP="30000000-0000-0000-0000-000000000002"
VIEWER_A_MEMBERSHIP="30000000-0000-0000-0000-000000000003"
MANAGER_A_SUBJECT="manager-a-alerts-acceptance"
MANAGER_B_SUBJECT="manager-b-alerts-acceptance"
VIEWER_A_SUBJECT="viewer-a-alerts-acceptance"

export POSTGRES_DB="nexolab"
export POSTGRES_USER="nexolab"
export POSTGRES_PASSWORD
export MINIO_ROOT_USER
export MINIO_ROOT_PASSWORD
export OBJECT_STORAGE_BUCKET="nexolab-alerts-acceptance"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="$API_PORT"
export CENTRAL_MQTT_PORT="$MQTT_PORT"
export CENTRAL_OBJECT_STORAGE_PORT="$OBJECT_STORAGE_PORT"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="$OBJECT_STORAGE_CONSOLE_PORT"
export MQTT_TOPIC="nexolab/telemetry"
export MQTT_CLIENT_ID="nexolab-alerts-browser-acceptance"
export CORS_ALLOWED_ORIGINS="$FRONTEND_BASE_URL"
export CORS_ALLOW_CREDENTIALS="false"
export AUTH_MODE="jwt"
export AUTH_DEFAULT_ORGANIZATION_ID="$ORGANIZATION_A"
export AUTH_JWT_PUBLIC_KEY="$JWT_SECRET"
export AUTH_JWT_ALGORITHM="HS256"
export AUTH_JWT_ISSUER="$JWT_ISSUER"
export AUTH_JWT_AUDIENCE="$JWT_AUDIENCE"
export AUTH_JWT_PROVIDER="$JWT_PROVIDER"
export RETENTION_ENABLED="false"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:${OBJECT_STORAGE_PORT}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${PROJECT_NAME}-mqtt-data"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${PROJECT_NAME}-postgres-data"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${PROJECT_NAME}-object-storage-data"
export ACCEPTANCE_NETWORK_NAME="${PROJECT_NAME}-network"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    -f "$COMPOSE_DIR/compose.central.yaml" \
    -f "$COMPOSE_DIR/compose.browser-acceptance.yaml" \
    "$@"
}

cleanup() {
  local status=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  compose ps --all >"${TMPDIR:-/tmp}/${PROJECT_NAME}-compose-ps.log" 2>&1 || true
  compose logs --no-color telemetry-service postgres mqtt >"$SERVICE_LOG" 2>&1 || true
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ $status -ne 0 ]]; then
    echo "Alerts browser acceptance failed. Frontend log:" >&2
    tail -n 160 "$FRONTEND_LOG" >&2 || true
    echo "Service log:" >&2
    tail -n 220 "$SERVICE_LOG" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

wait_for_url() {
  local url=$1
  local label=$2
  for _ in $(seq 1 90); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
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

for command in docker npm curl python3 mosquitto_pub; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is missing: $command" >&2
    exit 1
  fi
done

compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up -d --build mqtt postgres minio minio-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "telemetry service"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  ('$ORGANIZATION_A', 'alerts-org-a', 'Alerts Acceptance Organization A', true),
  ('$ORGANIZATION_B', 'alerts-org-b', 'Alerts Acceptance Organization B', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (
  id, provider, subject, email, display_name, is_active, last_authenticated_at
)
VALUES
  ('$MANAGER_A_ID', '$JWT_PROVIDER', '$MANAGER_A_SUBJECT', 'manager-a-alerts@nexolab.local', 'Manager A Alerts', true, now()),
  ('$MANAGER_B_ID', '$JWT_PROVIDER', '$MANAGER_B_SUBJECT', 'manager-b-alerts@nexolab.local', 'Manager B Alerts', true, now()),
  ('$VIEWER_A_ID', '$JWT_PROVIDER', '$VIEWER_A_SUBJECT', 'viewer-a-alerts@nexolab.local', 'Viewer A Alerts', true, now())
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email,
    display_name = EXCLUDED.display_name,
    is_active = true,
    last_authenticated_at = EXCLUDED.last_authenticated_at;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('$MANAGER_A_MEMBERSHIP', '$ORGANIZATION_A', '$MANAGER_A_ID', true),
  ('$MANAGER_B_MEMBERSHIP', '$ORGANIZATION_B', '$MANAGER_B_ID', true),
  ('$VIEWER_A_MEMBERSHIP', '$ORGANIZATION_A', '$VIEWER_A_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('$MANAGER_A_MEMBERSHIP', 'laboratory_manager', 'alerts-browser-acceptance'),
  ('$MANAGER_B_MEMBERSHIP', 'laboratory_manager', 'alerts-browser-acceptance'),
  ('$VIEWER_A_MEMBERSHIP', 'viewer', 'alerts-browser-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  < "$ROOT_DIR/scripts/security-acceptance-role-permissions.sql"

MANAGER_A_TOKEN="$(jwt_token "$MANAGER_A_SUBJECT" 'manager-a-alerts@nexolab.local' 'Manager A Alerts')"
MANAGER_B_TOKEN="$(jwt_token "$MANAGER_B_SUBJECT" 'manager-b-alerts@nexolab.local' 'Manager B Alerts')"
VIEWER_A_TOKEN="$(jwt_token "$VIEWER_A_SUBJECT" 'viewer-a-alerts@nexolab.local' 'Viewer A Alerts')"

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="$WEBSOCKET_URL"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_A"
export NEXT_TELEMETRY_DISABLED="1"

rm -f "$FRONTEND_LOG"
npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/alerts" "Next.js alerts workspace"

export NEXOLAB_ALERTS_BASE_URL="$FRONTEND_BASE_URL"
export NEXOLAB_ALERTS_API_BASE_URL="$API_BASE_URL"
export NEXOLAB_ALERTS_MQTT_HOST="127.0.0.1"
export NEXOLAB_ALERTS_MQTT_PORT="$MQTT_PORT"
export NEXOLAB_ALERTS_MQTT_TOPIC="$MQTT_TOPIC"
export NEXOLAB_ALERTS_ORGANIZATION_A="$ORGANIZATION_A"
export NEXOLAB_ALERTS_ORGANIZATION_B="$ORGANIZATION_B"
export NEXOLAB_ALERTS_MANAGER_A_TOKEN="$MANAGER_A_TOKEN"
export NEXOLAB_ALERTS_MANAGER_B_TOKEN="$MANAGER_B_TOKEN"
export NEXOLAB_ALERTS_VIEWER_A_TOKEN="$VIEWER_A_TOKEN"

npm run test:e2e:alerts

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
DO \$\$
DECLARE
  rule_count integer;
  alert_count integer;
  evidence_count integer;
  trigger_count integer;
  resolve_count integer;
  close_count integer;
  manager_actor_count integer;
BEGIN
  SELECT count(*) INTO rule_count
  FROM alert_rules
  WHERE name LIKE 'Acceptance high temperature %';
  IF rule_count <> 2 THEN
    RAISE EXCEPTION 'expected two organization-scoped rules, found %', rule_count;
  END IF;

  SELECT count(*) INTO alert_count
  FROM alert_instances
  WHERE organization_id = '$ORGANIZATION_A'
    AND state = 'closed'
    AND equipment_id = 'K106'
    AND channel_id = '106-03';
  IF alert_count <> 1 THEN
    RAISE EXCEPTION 'expected one closed acceptance alert, found %', alert_count;
  END IF;

  SELECT count(*) INTO evidence_count
  FROM alert_evidence_samples e
  JOIN alert_instances a ON a.id = e.alert_id
  WHERE a.organization_id = '$ORGANIZATION_A';
  IF evidence_count < 2 THEN
    RAISE EXCEPTION 'expected at least two evidence samples, found %', evidence_count;
  END IF;

  SELECT count(*) INTO trigger_count
  FROM alert_transitions t
  JOIN alert_instances a ON a.id = t.alert_id
  WHERE a.organization_id = '$ORGANIZATION_A'
    AND t.event_type = 'alert_triggered';
  IF trigger_count <> 1 THEN
    RAISE EXCEPTION 'expected one trigger transition, found %', trigger_count;
  END IF;

  SELECT count(*) INTO resolve_count
  FROM alert_transitions t
  JOIN alert_instances a ON a.id = t.alert_id
  WHERE a.organization_id = '$ORGANIZATION_A'
    AND t.event_type = 'alert_resolved';
  IF resolve_count <> 1 THEN
    RAISE EXCEPTION 'expected one resolve transition, found %', resolve_count;
  END IF;

  SELECT count(*) INTO close_count
  FROM alert_transitions t
  JOIN alert_instances a ON a.id = t.alert_id
  WHERE a.organization_id = '$ORGANIZATION_A'
    AND t.event_type = 'alert_closed';
  IF close_count <> 1 THEN
    RAISE EXCEPTION 'expected one close transition, found %', close_count;
  END IF;

  SELECT count(*) INTO manager_actor_count
  FROM alert_transitions t
  JOIN alert_instances a ON a.id = t.alert_id
  WHERE a.organization_id = '$ORGANIZATION_A'
    AND t.event_type IN ('alert_acknowledged', 'alert_closed')
    AND t.actor_id = '$MANAGER_A_SUBJECT';
  IF manager_actor_count <> 2 THEN
    RAISE EXCEPTION 'expected verified manager actor on acknowledge/close transitions, found %', manager_actor_count;
  END IF;
END \$\$;
SQL

echo "Alerts browser acceptance passed."
