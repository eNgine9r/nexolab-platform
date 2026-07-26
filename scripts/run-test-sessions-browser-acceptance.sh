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

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-sessions-acceptance-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${SESSIONS_API_PORT:-18112}"
export CENTRAL_MQTT_PORT="${SESSIONS_MQTT_PORT:-11914}"
export CENTRAL_OBJECT_STORAGE_PORT="${SESSIONS_OBJECT_STORAGE_PORT:-19030}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${SESSIONS_OBJECT_STORAGE_CONSOLE_PORT:-19031}"
export SESSIONS_WEB_PORT="${SESSIONS_WEB_PORT:-13030}"
export ACCEPTANCE_NETWORK_NAME="${ACCEPTANCE_NETWORK_NAME:-$COMPOSE_PROJECT_NAME-network}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${ACCEPTANCE_MQTT_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-mqtt}"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${ACCEPTANCE_POSTGRES_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-postgres}"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-object-storage}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-sessions-acceptance}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-sessions-images-acceptance}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$SESSIONS_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:sessions-acceptance}"

export AUTH_MODE="jwt"
export AUTH_DEFAULT_ORGANIZATION_ID="55555555-5555-4555-8555-555555555555"
export AUTH_JWT_PUBLIC_KEY="${AUTH_JWT_PUBLIC_KEY:-$(random_secret)}"
export AUTH_JWT_JWKS_URL=""
export AUTH_JWT_ALGORITHM="HS256"
export AUTH_JWT_ISSUER="https://identity.sessions-acceptance.test"
export AUTH_JWT_AUDIENCE="nexolab-api"
export AUTH_JWT_PROVIDER="acceptance-oidc"

export NEXOLAB_SESSIONS_ORGANIZATION_ID="$AUTH_DEFAULT_ORGANIZATION_ID"
export NEXOLAB_SESSIONS_OTHER_ORGANIZATION_ID="66666666-6666-4666-8666-666666666666"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$NEXOLAB_SESSIONS_ORGANIZATION_ID"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXOLAB_SESSIONS_WEB_URL="http://127.0.0.1:$SESSIONS_WEB_PORT"
export NEXOLAB_SESSIONS_BASE_COMPOSE="$BASE_COMPOSE"
export NEXOLAB_SESSIONS_ACCEPTANCE_COMPOSE="$ACCEPTANCE_COMPOSE"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_SESSIONS_EVIDENCE_DIR:-runtime/evidence/test-sessions-browser-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_SESSIONS_EVIDENCE_DIR="$EVIDENCE_DIR"
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
    >"$EVIDENCE_DIR/test-sessions-database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT organization_id, session_number, state, lock_version,
       active_limit_version, current_stage_id, active_config_snapshot_id
FROM test_sessions
ORDER BY organization_id, session_number;

SELECT s.organization_id, e.event_type, e.actor_id, e.actor_source,
       e.previous_state, e.next_state, e.occurred_at
FROM session_events e
JOIN test_sessions s ON s.id = e.session_id
ORDER BY s.organization_id, e.occurred_at, e.id;

SELECT s.organization_id, COUNT(*) AS bindings
FROM session_channel_bindings b
JOIN test_sessions s ON s.id = b.session_id
GROUP BY s.organization_id
ORDER BY s.organization_id;

SELECT event_id, session_id, stage_id, binding_id, captured_at
FROM telemetry_session_contexts
ORDER BY captured_at, event_id;
SQL

  python3 - <<'PY' >"$EVIDENCE_DIR/test-sessions-runtime.json" || true
import json
import os

print(json.dumps({
    "webUrl": os.environ["NEXOLAB_SESSIONS_WEB_URL"],
    "apiOrigin": os.environ["NEXT_PUBLIC_NEXOLAB_API_BASE_URL"],
    "organizationId": os.environ["NEXOLAB_SESSIONS_ORGANIZATION_ID"],
    "otherOrganizationId": os.environ["NEXOLAB_SESSIONS_OTHER_ORGANIZATION_ID"],
    "authMode": os.environ["AUTH_MODE"],
    "authProvider": os.environ["AUTH_JWT_PROVIDER"],
}, indent=2))
PY
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_SESSIONS_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nTest sessions acceptance evidence: %s\n' "$EVIDENCE_DIR"
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
  printf 'Test sessions acceptance stack did not become ready.\n' >&2
  exit 1
fi

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v organization_id="$NEXOLAB_SESSIONS_ORGANIZATION_ID" \
  -v other_organization_id="$NEXOLAB_SESSIONS_OTHER_ORGANIZATION_ID" <<'SQL'
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  (:'organization_id', 'sessions-acceptance-a', 'NEXOLAB Sessions Acceptance A', true),
  (:'other_organization_id', 'sessions-acceptance-b', 'NEXOLAB Sessions Acceptance B', true)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES
  ('77777777-7777-4777-8777-777777777701', 'acceptance-oidc', 'viewer-sessions-acceptance', 'viewer-sessions@example.test', 'Viewer Sessions Acceptance', true),
  ('77777777-7777-4777-8777-777777777702', 'acceptance-oidc', 'engineer-a-acceptance', 'engineer-a@example.test', 'Engineer A Acceptance', true),
  ('77777777-7777-4777-8777-777777777703', 'acceptance-oidc', 'engineer-b-acceptance', 'engineer-b@example.test', 'Engineer B Acceptance', true)
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email, display_name = EXCLUDED.display_name, is_active = true;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('88888888-8888-4888-8888-888888888801', :'organization_id', '77777777-7777-4777-8777-777777777701', true),
  ('88888888-8888-4888-8888-888888888802', :'organization_id', '77777777-7777-4777-8777-777777777702', true),
  ('88888888-8888-4888-8888-888888888803', :'other_organization_id', '77777777-7777-4777-8777-777777777703', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('88888888-8888-4888-8888-888888888801', 'viewer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888802', 'engineer', 'sessions-acceptance-seed'),
  ('88888888-8888-4888-8888-888888888803', 'engineer', 'sessions-acceptance-seed')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL

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

for variable, subject, name in (
    ('NEXOLAB_SESSIONS_VIEWER_TOKEN', 'viewer-sessions-acceptance', 'Viewer Sessions Acceptance'),
    ('NEXOLAB_SESSIONS_ENGINEER_A_TOKEN', 'engineer-a-acceptance', 'Engineer A Acceptance'),
    ('NEXOLAB_SESSIONS_ENGINEER_B_TOKEN', 'engineer-b-acceptance', 'Engineer B Acceptance'),
):
    print(f'export {variable}={token(subject, name)}')
PY
)"

npm run build
npm run test:e2e:sessions
