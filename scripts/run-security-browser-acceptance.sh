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

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-security-acceptance-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${SECURITY_API_PORT:-18092}"
export CENTRAL_MQTT_PORT="${SECURITY_MQTT_PORT:-11894}"
export CENTRAL_OBJECT_STORAGE_PORT="${SECURITY_OBJECT_STORAGE_PORT:-19010}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${SECURITY_OBJECT_STORAGE_CONSOLE_PORT:-19011}"
export SECURITY_WEB_PORT="${SECURITY_WEB_PORT:-13010}"
export ACCEPTANCE_NETWORK_NAME="${ACCEPTANCE_NETWORK_NAME:-$COMPOSE_PROJECT_NAME-network}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${ACCEPTANCE_MQTT_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-mqtt}"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${ACCEPTANCE_POSTGRES_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-postgres}"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-object-storage}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-security-acceptance}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-security-images-acceptance}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$SECURITY_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:security-acceptance}"

export AUTH_MODE="jwt"
export AUTH_DEFAULT_ORGANIZATION_ID="11111111-1111-1111-1111-111111111111"
export AUTH_JWT_PUBLIC_KEY="${AUTH_JWT_PUBLIC_KEY:-$(random_secret)}"
export AUTH_JWT_JWKS_URL=""
export AUTH_JWT_ALGORITHM="HS256"
export AUTH_JWT_ISSUER="https://identity.security-acceptance.test"
export AUTH_JWT_AUDIENCE="nexolab-api"
export AUTH_JWT_PROVIDER="acceptance-oidc"

export NEXOLAB_SECURITY_ORGANIZATION_ID="$AUTH_DEFAULT_ORGANIZATION_ID"
export NEXOLAB_SECURITY_OTHER_ORGANIZATION_ID="22222222-2222-2222-2222-222222222222"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/ws/telemetry"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$NEXOLAB_SECURITY_ORGANIZATION_ID"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXOLAB_SECURITY_WEB_URL="http://127.0.0.1:$SECURITY_WEB_PORT"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_SECURITY_EVIDENCE_DIR:-runtime/evidence/security-browser-acceptance-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_SECURITY_EVIDENCE_DIR="$EVIDENCE_DIR"
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
    >"$EVIDENCE_DIR/security-database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT o.slug, i.subject, array_agg(r.role ORDER BY r.role) AS roles
FROM security_organizations o
JOIN security_organization_memberships m ON m.organization_id = o.id
JOIN security_identities i ON i.id = m.identity_id
JOIN security_membership_roles r ON r.membership_id = m.id
GROUP BY o.slug, i.subject
ORDER BY o.slug, i.subject;

SELECT action, entity_type, entity_id, actor_subject, actor_roles, reason, occurred_at
FROM security_audit_events
ORDER BY occurred_at, id;

SELECT organization_id, equipment_id, version, image_id, json_array_length(placements) AS placements
FROM refrigeration_layout_drafts
ORDER BY organization_id, equipment_id;

SELECT organization_id, equipment_id, revision, published_by, published_at
FROM refrigeration_layout_revisions
ORDER BY organization_id, equipment_id, revision;
SQL
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_SECURITY_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nSecurity acceptance evidence: %s\n' "$EVIDENCE_DIR"
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
  printf 'Security acceptance stack did not become ready.\n' >&2
  exit 1
fi

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v organization_id="$NEXOLAB_SECURITY_ORGANIZATION_ID" \
  -v other_organization_id="$NEXOLAB_SECURITY_OTHER_ORGANIZATION_ID" <<'SQL'
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  (:'organization_id', 'security-acceptance', 'NEXOLAB Security Acceptance', true),
  (:'other_organization_id', 'other-security-lab', 'Other Security Laboratory', true)
ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (id, provider, subject, email, display_name, is_active)
VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 'acceptance-oidc', 'viewer-acceptance', 'viewer@example.test', 'Viewer Acceptance', true),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 'acceptance-oidc', 'operator-acceptance', 'operator@example.test', 'Operator Acceptance', true),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', 'acceptance-oidc', 'engineer-acceptance', 'engineer@example.test', 'Engineer Acceptance', true),
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4', 'acceptance-oidc', 'administrator-acceptance', 'administrator@example.test', 'Administrator Acceptance', true)
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email, display_name = EXCLUDED.display_name, is_active = true;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', :'organization_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', true),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', :'organization_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', true),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', :'organization_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', true),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb4', :'organization_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa4', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'viewer', 'acceptance-seed'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', 'operator', 'acceptance-seed'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', 'engineer', 'acceptance-seed'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb4', 'administrator', 'acceptance-seed')
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
    ('NEXOLAB_VIEWER_TOKEN', 'viewer-acceptance', 'Viewer Acceptance'),
    ('NEXOLAB_OPERATOR_TOKEN', 'operator-acceptance', 'Operator Acceptance'),
    ('NEXOLAB_ENGINEER_TOKEN', 'engineer-acceptance', 'Engineer Acceptance'),
    ('NEXOLAB_ADMIN_TOKEN', 'administrator-acceptance', 'Administrator Acceptance'),
):
    print(f'export {variable}={token(subject, name)}')
PY
)"

npm run build
npm run test:e2e:security
