#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SUFFIX="$(date -u +%Y%m%dt%H%M%Sz)-$$"
NETWORK_NAME="nexolab-local-auth-migration-$RUN_SUFFIX"
POSTGRES_CONTAINER="nexolab-local-auth-migration-postgres-$RUN_SUFFIX"
TELEMETRY_IMAGE="nexolab-telemetry-service:local-auth-migration-$RUN_SUFFIX"
DATABASE_NAME="nexolab_auth_migration"
DATABASE_USER="nexolab"
DATABASE_PASSWORD="$(openssl rand -hex 24)"
DATABASE_URL="postgresql+psycopg://${DATABASE_USER}:${DATABASE_PASSWORD}@${POSTGRES_CONTAINER}:5432/${DATABASE_NAME}"
EVIDENCE_DIR="${NEXOLAB_LOCAL_AUTH_MIGRATION_EVIDENCE_DIR:-runtime/evidence/offline-auth-acceptance-migration-$RUN_SUFFIX}"

if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
mkdir -p "$EVIDENCE_DIR"

cleanup() {
  docker rm --force "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK_NAME" >/dev/null 2>&1 || true
  docker image rm "$TELEMETRY_IMAGE" >/dev/null 2>&1 || true
  unset DATABASE_PASSWORD DATABASE_URL
}
trap cleanup EXIT

for command in docker openssl; do
  command -v "$command" >/dev/null || {
    printf 'Required command is missing: %s\n' "$command" >&2
    exit 1
  }
done

cd "$ROOT_DIR"
docker network create "$NETWORK_NAME" >/dev/null

docker run --detach \
  --name "$POSTGRES_CONTAINER" \
  --network "$NETWORK_NAME" \
  --env "POSTGRES_DB=$DATABASE_NAME" \
  --env "POSTGRES_USER=$DATABASE_USER" \
  --env "POSTGRES_PASSWORD=$DATABASE_PASSWORD" \
  postgres:16-alpine >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$POSTGRES_CONTAINER" \
    pg_isready -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

docker exec "$POSTGRES_CONTAINER" \
  pg_isready -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null

docker build \
  --tag "$TELEMETRY_IMAGE" \
  services/telemetry-service >/dev/null

run_alembic() {
  docker run --rm \
    --network "$NETWORK_NAME" \
    --env "DATABASE_URL=$DATABASE_URL" \
    "$TELEMETRY_IMAGE" \
    alembic "$@"
}

query_database() {
  docker exec "$POSTGRES_CONTAINER" \
    psql \
    --username "$DATABASE_USER" \
    --dbname "$DATABASE_NAME" \
    --tuples-only \
    --no-align \
    --command "$1"
}

run_alembic upgrade head >/dev/null
UPGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$UPGRADED_REVISION" == *"20260801_0021"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NOT NULL AND to_regclass('public.security_local_sessions') IS NOT NULL;")" == "t" ]]

run_alembic downgrade 20260731_0021 >/dev/null
DOWNGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$DOWNGRADED_REVISION" == *"20260731_0021"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NULL AND to_regclass('public.security_local_sessions') IS NULL;")" == "t" ]]

run_alembic upgrade head >/dev/null
REUPGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$REUPGRADED_REVISION" == *"20260801_0021"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NOT NULL AND to_regclass('public.security_local_sessions') IS NOT NULL;")" == "t" ]]

cat >"$EVIDENCE_DIR/migration-roundtrip.txt" <<EOF
upgrade_revision=$UPGRADED_REVISION
downgrade_revision=$DOWNGRADED_REVISION
reupgrade_revision=$REUPGRADED_REVISION
local_auth_tables_after_upgrade=present
local_auth_tables_after_downgrade=absent
local_auth_tables_after_reupgrade=present
status=passed
EOF

printf 'Local-auth migration round-trip passed. Evidence: %s\n' "$EVIDENCE_DIR"
