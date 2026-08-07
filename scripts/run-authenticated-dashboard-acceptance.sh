#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/compose.central.yaml"
ACCEPTANCE_COMPOSE="$COMPOSE_DIR/compose.browser-acceptance.yaml"
RUN_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$$"

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    printf '%s' "${RUN_SUFFIX//[^a-zA-Z0-9]/}$(date +%s%N)"
  fi
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-dashboard-acceptance-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${DASHBOARD_API_PORT:-18102}"
export CENTRAL_MQTT_PORT="${DASHBOARD_MQTT_PORT:-11904}"
export CENTRAL_OBJECT_STORAGE_PORT="${DASHBOARD_OBJECT_STORAGE_PORT:-19020}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${DASHBOARD_OBJECT_STORAGE_CONSOLE_PORT:-19021}"
export DASHBOARD_WEB_PORT="${DASHBOARD_WEB_PORT:-13020}"
export ACCEPTANCE_NETWORK_NAME="${ACCEPTANCE_NETWORK_NAME:-$COMPOSE_PROJECT_NAME-network}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${ACCEPTANCE_MQTT_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-mqtt}"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${ACCEPTANCE_POSTGRES_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-postgres}"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-object-storage}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-dashboard-acceptance}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-dashboard-images-acceptance}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$DASHBOARD_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:dashboard-acceptance}"

export AUTH_MODE="jwt"
export AUTH_DEFAULT_ORGANIZATION_ID="33333333-3333-3333-3333-333333333333"
export AUTH_JWT_PUBLIC_KEY="${AUTH_JWT_PUBLIC_KEY:-$(random_secret)}"
export AUTH_JWT_JWKS_URL=""
export AUTH_JWT_ALGORITHM="HS256"
export AUTH_JWT_ISSUER="https://identity.dashboard-acceptance.test"
export AUTH_JWT_AUDIENCE="nexolab-api"
export AUTH_JWT_PROVIDER="acceptance-oidc"

export NEXOLAB_DASHBOARD_ORGANIZATION_ID="$AUTH_DEFAULT_ORGANIZATION_ID"
export NEXOLAB_DASHBOARD_OTHER_ORGANIZATION_ID="44444444-4444-4444-4444-444444444444"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$NEXOLAB_DASHBOARD_ORGANIZATION_ID"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXOLAB_DASHBOARD_WEB_URL="http://127.0.0.1:$DASHBOARD_WEB_PORT"
export NEXOLAB_DASHBOARD_BASE_COMPOSE="$BASE_COMPOSE"
export NEXOLAB_DASHBOARD_ACCEPTANCE_COMPOSE="$ACCEPTANCE_COMPOSE"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_DASHBOARD_EVIDENCE_DIR:-runtime/evidence/authenticated-dashboard-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_DASHBOARD_EVIDENCE_DIR="$EVIDENCE_DIR"
mkdir -p "$EVIDENCE_DIR"

STACK_STARTED=0

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --file "$BASE_COMPOSE" \
    --file "$ACCEPTANCE_COMPOSE" \
    "$@"
}

collect_evidence() {
  if [[ "$STACK_STARTED" != "1" ]]; then
    return 0
  fi

  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color >"$EVIDENCE_DIR/central-stack.log" 2>&1 || true
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/dashboard-database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT o.slug, i.subject, array_agg(r.role ORDER BY r.role) AS roles
FROM security_organizations o
JOIN security_organization_memberships m ON m.organization_id = o.id
JOIN security_identities i ON i.id = m.identity_id
JOIN security_membership_roles r ON r.membership_id = m.id
GROUP BY o.slug, i.subject
ORDER BY o.slug, i.subject;

SELECT event_id, node_id, equipment_id, channel_id, metric, value, unit, quality, captured_at
FROM telemetry_samples
ORDER BY captured_at, event_id;
SQL

  python3 - <<'PY' >"$EVIDENCE_DIR/dashboard-runtime.json" || true
import json
import os

print(json.dumps({
    "webUrl": os.environ["NEXOLAB_DASHBOARD_WEB_URL"],
    "apiOrigin": os.environ["NEXT_PUBLIC_NEXOLAB_API_BASE_URL"],
    "websocketOrigin": os.environ["NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL"],
    "organizationId": os.environ["NEXOLAB_DASHBOARD_ORGANIZATION_ID"],
    "authMode": os.environ["AUTH_MODE"],
    "authProvider": os.environ["AUTH_JWT_PROVIDER"],
}, indent=2))
PY
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_DASHBOARD_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nAuthenticated dashboard evidence: %s\n' "$EVIDENCE_DIR"
  exit "$status"
}
trap on_exit EXIT

for command in docker npm curl python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "$command" >&2
    exit 1
  fi
done

cd "$ROOT_DIR"
npm install --no-audit --no-fund
if [[ "${PLAYWRIGHT_INSTALL_WITH_DEPS:-0}" == "1" ]]; then
  npx playwright install --with-deps chromium
else
  npx playwright install chromium
fi

compose up --detach --build
STACK_STARTED=1

ready=0
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  printf 'Authenticated dashboard stack did not become ready.\n' >&2
  exit 1
fi

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v organization_id="$NEXOLAB_DASHBOARD_ORGANIZATION_ID" \
  -v other_organization_id="$NEXOLAB_DASHBOARD_OTHER_ORGANIZATION_ID" <<'SQL'
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  (:'organization_id', 'dashboard-acceptance', 'NEXOLAB Dashboard Acceptance', true),
  (:'other_organization_id', 'other-dashboard-lab', 'Other Dashboard Laboratory', true)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES (
  'cccccccc-cccc-cccc-cccc-ccccccccccc1',
  'acceptance-oidc',
  'viewer-acceptance',
  'viewer@example.test',
  'Viewer Acceptance',
  true
)
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email, display_name = EXCLUDED.display_name, is_active = true;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES (
  'dddddddd-dddd-dddd-dddd-ddddddddddd1',
  :'organization_id',
  'cccccccc-cccc-cccc-cccc-ccccccccccc1',
  true
)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES ('dddddddd-dddd-dddd-dddd-ddddddddddd1', 'viewer', 'dashboard-acceptance-seed')
ON CONFLICT (membership_id, role) DO NOTHING;

INSERT INTO telemetry_samples (
  event_id,
  node_id,
  captured_at,
  metric,
  value,
  unit,
  quality,
  source,
  equipment_id,
  channel_id,
  alarm,
  raw_value,
  raw_status,
  raw_payload
)
VALUES
  (
    '10000000-0000-4000-8000-000000000001',
    'edge-live-01',
    NOW() - INTERVAL '23 hours',
    'temperature.probe',
    4.1,
    'degC',
    'valid',
    'dashboard-acceptance',
    'K106',
    '106-03',
    NULL,
    41,
    4354,
    '{}'::json
  ),
  (
    '10000000-0000-4000-8000-000000000002',
    'edge-live-01',
    NOW() - INTERVAL '2 hours',
    'temperature.probe',
    4.3,
    'degC',
    'valid',
    'dashboard-acceptance',
    'K106',
    '106-03',
    NULL,
    43,
    4354,
    '{}'::json
  ),
  (
    '10000000-0000-4000-8000-000000000003',
    'edge-live-01',
    NOW() - INTERVAL '15 minutes',
    'temperature.probe',
    4.5,
    'degC',
    'valid',
    'dashboard-acceptance',
    'K106',
    '106-03',
    NULL,
    45,
    4354,
    '{}'::json
  ),
  (
    '10000000-0000-4000-8000-000000000004',
    'edge-live-01',
    NOW() - INTERVAL '12 minutes',
    'temperature.probe',
    3.9,
    'degC',
    'valid',
    'dashboard-acceptance',
    'K106',
    '106-04',
    NULL,
    39,
    4354,
    '{}'::json
  ),
  (
    '10000000-0000-4000-8000-000000000005',
    'edge-live-02',
    NOW() - INTERVAL '1 minute',
    'active_power',
    1.25,
    'kW',
    'valid',
    'dashboard-acceptance',
    'M200',
    '200-01',
    NULL,
    1250,
    NULL,
    '{}'::json
  )
ON CONFLICT (event_id) DO NOTHING;
SQL

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  < "$ROOT_DIR/scripts/security-acceptance-role-permissions.sql"

eval "$(python3 - <<'PY'
import base64
import hashlib
import hmac
import json
import os
import time

secret = os.environ['AUTH_JWT_PUBLIC_KEY'].encode()
issuer = os.environ['AUTH_JWT_ISSUER']
audience = os.environ['AUTH_JWT_AUDIENCE']

def encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()

def token(subject, name):
    now = int(time.time())
    header = encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    payload = encode(json.dumps({
        'sub': subject,
        'email': f'{subject}@example.test',
        'name': name,
        'iss': issuer,
        'aud': audience,
        'iat': now,
        'exp': now + 1800,
    }, separators=(',', ':')).encode())
    signature = encode(hmac.new(secret, f'{header}.{payload}'.encode(), hashlib.sha256).digest())
    return f'{header}.{payload}.{signature}'

print(f'export NEXOLAB_DASHBOARD_VIEWER_TOKEN={token("viewer-acceptance", "Viewer Acceptance")}')
PY
)"

npm run build
npm run test:e2e:dashboard
