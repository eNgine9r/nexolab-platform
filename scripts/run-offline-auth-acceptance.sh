#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/compose.central.yaml"
LOCAL_AUTH_COMPOSE="$COMPOSE_DIR/compose.local-auth.yaml"
ACCEPTANCE_COMPOSE="$COMPOSE_DIR/compose.local-auth-acceptance.yaml"
RUN_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$$"
SECRET_DIR="$(mktemp -d)"
PASSWORD_FILE="$SECRET_DIR/operator-password"
PRIVATE_KEY_FILE="$SECRET_DIR/private.pem"
PUBLIC_KEY_FILE="$SECRET_DIR/public.pem"

random_secret() {
  openssl rand -hex 24
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-local-auth-acceptance-$RUN_SUFFIX}"
export CENTRAL_RESOURCE_PREFIX="$COMPOSE_PROJECT_NAME"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${LOCAL_AUTH_API_PORT:-18093}"
export CENTRAL_MQTT_PORT="${LOCAL_AUTH_MQTT_PORT:-11895}"
export CENTRAL_OBJECT_STORAGE_PORT="${LOCAL_AUTH_OBJECT_STORAGE_PORT:-19012}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${LOCAL_AUTH_OBJECT_STORAGE_CONSOLE_PORT:-19013}"
export LOCAL_AUTH_WEB_PORT="${LOCAL_AUTH_WEB_PORT:-13011}"
export ACCEPTANCE_NETWORK_NAME="$COMPOSE_PROJECT_NAME-network"
export ACCEPTANCE_MQTT_VOLUME_NAME="$COMPOSE_PROJECT_NAME-mqtt"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="$COMPOSE_PROJECT_NAME-postgres"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="$COMPOSE_PROJECT_NAME-object-storage"
export POSTGRES_DB="nexolab"
export POSTGRES_USER="nexolab"
export POSTGRES_PASSWORD="$(random_secret)"
export MINIO_ROOT_USER="nexolab-local-auth-acceptance"
export MINIO_ROOT_PASSWORD="$(random_secret)"
export OBJECT_STORAGE_BUCKET="nexolab-local-auth-acceptance"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$LOCAL_AUTH_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="nexolab-telemetry-service:local-auth-acceptance"

export AUTH_MODE="disabled"
export AUTH_DEFAULT_ORGANIZATION_ID="11111111-1111-1111-1111-111111111111"
export AUTH_LOCAL_PRIVATE_KEY_HOST_FILE="$PRIVATE_KEY_FILE"
export AUTH_LOCAL_PUBLIC_KEY_HOST_FILE="$PUBLIC_KEY_FILE"
export AUTH_LOCAL_ISSUER="urn:nexolab:local-auth-acceptance"
export AUTH_LOCAL_AUDIENCE="nexolab-api"
export AUTH_LOCAL_ACCESS_TOKEN_SECONDS="300"
export AUTH_LOCAL_REFRESH_TOKEN_SECONDS="3600"
export AUTH_LOCAL_MAX_FAILED_ATTEMPTS="5"
export AUTH_LOCAL_LOCKOUT_SECONDS="60"

export NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID="$AUTH_DEFAULT_ORGANIZATION_ID"
export NEXOLAB_LOCAL_AUTH_VIEWER_USERNAME="viewer"
export NEXOLAB_LOCAL_AUTH_OPERATOR_USERNAME="operator"
export NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME="administrator"
export NEXOLAB_LOCAL_AUTH_PASSWORD="Local-Acceptance-$(random_secret)"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="local"
export NEXOLAB_LOCAL_AUTH_WEB_URL="http://127.0.0.1:$LOCAL_AUTH_WEB_PORT"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR:-runtime/evidence/offline-auth-acceptance-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_LOCAL_AUTH_EVIDENCE_DIR="$EVIDENCE_DIR"
mkdir -p "$EVIDENCE_DIR"
chmod 0700 "$SECRET_DIR"
printf '%s' "$NEXOLAB_LOCAL_AUTH_PASSWORD" >"$PASSWORD_FILE"
chmod 0600 "$PASSWORD_FILE"

STACK_STARTED=0

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --file "$BASE_COMPOSE" \
    --file "$LOCAL_AUTH_COMPOSE" \
    --file "$ACCEPTANCE_COMPOSE" \
    "$@"
}

collect_evidence() {
  if [[ "$STACK_STARTED" != "1" ]]; then
    return 0
  fi
  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color >"$EVIDENCE_DIR/central-stack.log" 2>&1 || true
  docker network inspect "$ACCEPTANCE_NETWORK_NAME" \
    --format '{{json .}}' >"$EVIDENCE_DIR/network.json" 2>&1 || true
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/local-auth-database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT a.username,
       i.provider,
       i.subject,
       m.organization_id,
       array_agg(r.role ORDER BY r.role) AS roles,
       a.is_active,
       a.failed_login_count,
       a.locked_until
FROM security_local_accounts a
JOIN security_identities i ON i.id = a.identity_id
JOIN security_organization_memberships m ON m.identity_id = i.id
JOIN security_membership_roles r ON r.membership_id = m.id
GROUP BY a.username, i.provider, i.subject, m.organization_id,
         a.is_active, a.failed_login_count, a.locked_until
ORDER BY a.username;

SELECT count(*) AS session_count,
       count(*) FILTER (WHERE revoked_at IS NULL) AS active_sessions,
       count(*) FILTER (WHERE revoked_at IS NOT NULL) AS revoked_sessions
FROM security_local_sessions;

SELECT action, actor_subject, actor_roles, entity_type, occurred_at
FROM security_audit_events
WHERE action LIKE 'security.local_%'
ORDER BY occurred_at, id;
SQL
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_LOCAL_AUTH_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$SECRET_DIR"
  unset NEXOLAB_LOCAL_AUTH_PASSWORD POSTGRES_PASSWORD MINIO_ROOT_PASSWORD
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nOffline local-auth acceptance evidence: %s\n' "$EVIDENCE_DIR"
  exit "$status"
}
trap on_exit EXIT

for command in docker npm curl python3 openssl; do
  command -v "$command" >/dev/null || {
    printf 'Required command is missing: %s\n' "$command" >&2
    exit 1
  }
done

openssl genpkey \
  -algorithm RSA \
  -pkeyopt rsa_keygen_bits:3072 \
  -out "$PRIVATE_KEY_FILE" >/dev/null 2>&1
openssl pkey \
  -in "$PRIVATE_KEY_FILE" \
  -pubout \
  -out "$PUBLIC_KEY_FILE" >/dev/null 2>&1
chmod 0600 "$PRIVATE_KEY_FILE"
chmod 0644 "$PUBLIC_KEY_FILE"

cd "$ROOT_DIR"
compose config --quiet
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
  printf 'Local-auth acceptance stack did not become ready.\n' >&2
  exit 1
fi

if [[ "$(docker network inspect "$ACCEPTANCE_NETWORK_NAME" --format '{{.Internal}}')" != "true" ]]; then
  printf 'Acceptance network is not internal.\n' >&2
  exit 1
fi

if compose exec -T telemetry-service python - <<'PY'
import urllib.request

try:
    urllib.request.urlopen("https://example.com", timeout=3)
except Exception:
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  printf 'Telemetry Service unexpectedly reached the public internet.\n' >&2
  exit 1
fi
printf 'container-egress=blocked\n' >"$EVIDENCE_DIR/runtime-network-boundary.txt"

create_account() {
  local username="$1" role="$2" display_name="$3"
  compose run --rm --no-deps \
    -v "$PASSWORD_FILE:/run/operator-password:ro" \
    telemetry-service \
    python -m app.security.local_cli create-account \
    --username "$username" \
    --password-file /run/operator-password \
    --display-name "$display_name" \
    --organization-id "$NEXOLAB_LOCAL_AUTH_ORGANIZATION_ID" \
    --organization-slug nexolab-acceptance \
    --organization-name "NEXOLAB Local Auth Acceptance" \
    --role "$role"
}

create_account "$NEXOLAB_LOCAL_AUTH_VIEWER_USERNAME" viewer "Local Viewer"
create_account "$NEXOLAB_LOCAL_AUTH_OPERATOR_USERNAME" operator "Local Operator"
create_account "$NEXOLAB_LOCAL_AUTH_ADMIN_USERNAME" administrator "Local Administrator"

npm ci --no-audit --no-fund
if [[ "${PLAYWRIGHT_INSTALL_WITH_DEPS:-0}" == "1" ]]; then
  npx playwright install --with-deps chromium
else
  npx playwright install chromium
fi
npm run build
npx playwright test --config=playwright.local-auth.config.ts
