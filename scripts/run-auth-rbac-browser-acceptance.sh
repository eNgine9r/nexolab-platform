#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/compose.central.yaml"
ACCEPTANCE_COMPOSE="$COMPOSE_DIR/compose.browser-acceptance.yaml"
RUN_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$$"

random_secret() {
  openssl rand -hex 32
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-rbac-acceptance-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${RBAC_API_PORT:-28082}"
export CENTRAL_MQTT_PORT="${RBAC_MQTT_PORT:-21884}"
export CENTRAL_OBJECT_STORAGE_PORT="${RBAC_OBJECT_STORAGE_PORT:-29000}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${RBAC_OBJECT_STORAGE_CONSOLE_PORT:-29001}"
export RBAC_WEB_PORT="${RBAC_WEB_PORT:-23000}"
export ACCEPTANCE_NETWORK_NAME="${ACCEPTANCE_NETWORK_NAME:-$COMPOSE_PROJECT_NAME-network}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${ACCEPTANCE_MQTT_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-mqtt}"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${ACCEPTANCE_POSTGRES_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-postgres}"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-object-storage}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-rbac-acceptance}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-equipment-images-rbac}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$RBAC_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:rbac-acceptance}"

export AUTH_MODE="jwt"
export AUTH_JWT_SECRET="${AUTH_JWT_SECRET:-$(random_secret)}"
export AUTH_JWT_ISSUER="${AUTH_JWT_ISSUER:-https://auth.nexolab.acceptance}"
export AUTH_JWT_AUDIENCE="${AUTH_JWT_AUDIENCE:-nexolab-api}"
export AUTH_JWT_LEEWAY_SECONDS="0"
export AUTH_DEFAULT_ORGANIZATION_ID="nexolab-default"
export AUTH_AUTO_PROVISION_MEMBERSHIPS="true"

export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_OPERATOR_ID="rbac-browser-operator"
export NEXOLAB_RBAC_WEB_URL="http://127.0.0.1:$RBAC_WEB_PORT"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_RBAC_EVIDENCE_DIR:-runtime/evidence/auth-rbac-browser-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_RBAC_EVIDENCE_DIR="$EVIDENCE_DIR"
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
    >"$EVIDENCE_DIR/postgresql-auth-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT id, slug, is_active FROM organizations ORDER BY id;
SELECT subject, email, is_active FROM auth_identities ORDER BY subject;
SELECT organization_id, role, is_active FROM organization_memberships ORDER BY organization_id, role;
SELECT organization_id, resource_type, resource_id FROM resource_organization_bindings ORDER BY organization_id, resource_type, resource_id;
SELECT organization_id, actor_subject, actor_role, action, outcome, resource_type, resource_id, occurred_at
FROM platform_audit_events
ORDER BY occurred_at;
SQL
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_RBAC_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nRBAC acceptance evidence: %s\n' "$EVIDENCE_DIR"
  exit "$status"
}
trap on_exit EXIT

for command in docker npm curl openssl; do
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
    "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null 2>&1 && \
    curl --fail --silent --show-error \
      "http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT/minio/health/live" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" != "1" ]]; then
  printf 'RBAC central acceptance stack did not become ready.\n' >&2
  exit 1
fi

npm run build
npx playwright test --config=playwright.rbac.config.ts
