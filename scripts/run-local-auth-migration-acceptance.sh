#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_SUFFIX="$(date -u +%Y%m%dt%H%M%Sz)-$$"
NETWORK_NAME="nexolab-local-auth-migration-$RUN_SUFFIX"
POSTGRES_CONTAINER="nexolab-local-auth-migration-postgres-$RUN_SUFFIX"
POSTGRES_IMAGE="postgres:16-alpine"
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

postgres_diagnostics() {
  local reason="$1"
  local attempt="${2:-0}"

  printf 'PostgreSQL acceptance bootstrap diagnostic: reason=%s attempt=%s\n' \
    "$reason" "$attempt" >&2
  docker version --format \
    'docker_client={{.Client.Version}} docker_server={{.Server.Version}}' >&2 || true
  docker image inspect "$POSTGRES_IMAGE" --format \
    'postgres_image_id={{.Id}} postgres_repo_digests={{json .RepoDigests}}' >&2 || true
  docker network inspect "$NETWORK_NAME" --format \
    'network={{.Name}} driver={{.Driver}} scope={{.Scope}}' >&2 || true
  docker inspect "$POSTGRES_CONTAINER" --format \
    'container={{.Name}} status={{.State.Status}} exit_code={{.State.ExitCode}} error={{json .State.Error}}' >&2 || true
  docker logs --tail 50 "$POSTGRES_CONTAINER" >&2 || true
}

start_postgres_container() {
  local postgres_image_id="$1"
  local max_attempts=2
  local attempt

  for attempt in $(seq 1 "$max_attempts"); do
    docker rm --force "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true

    if docker run --detach \
      --pull=never \
      --name "$POSTGRES_CONTAINER" \
      --network "$NETWORK_NAME" \
      --env "POSTGRES_DB=$DATABASE_NAME" \
      --env "POSTGRES_USER=$DATABASE_USER" \
      --env "POSTGRES_PASSWORD=$DATABASE_PASSWORD" \
      "$postgres_image_id" >/dev/null; then
      return 0
    fi

    postgres_diagnostics "container_create_failed" "$attempt"

    if ((attempt < max_attempts)); then
      docker rm --force "$POSTGRES_CONTAINER" >/dev/null 2>&1 || true
      sleep 1
    fi
  done

  printf 'PostgreSQL acceptance container creation failed after %s attempts.\n' \
    "$max_attempts" >&2
  return 1
}

wait_for_postgres() {
  local ready=false
  local state

  for _ in $(seq 1 60); do
    if docker exec "$POSTGRES_CONTAINER" \
      pg_isready -U "$DATABASE_USER" -d "$DATABASE_NAME" >/dev/null 2>&1; then
      ready=true
      break
    fi

    state="$(docker inspect "$POSTGRES_CONTAINER" --format '{{.State.Status}}' 2>/dev/null || true)"
    if [[ -z "$state" || "$state" == "exited" || "$state" == "dead" ]]; then
      postgres_diagnostics "container_not_running_before_ready"
      return 1
    fi

    sleep 1
  done

  if [[ "$ready" != "true" ]]; then
    postgres_diagnostics "readiness_timeout"
    return 1
  fi
}

cd "$ROOT_DIR"
docker network create "$NETWORK_NAME" >/dev/null

# Keep image acquisition separate from container creation. This prevents an
# implicit pull/create path from turning a transient Docker bootstrap failure
# into an opaque acceptance failure and makes the container run against the
# exact image ID that was inspected immediately before startup.
docker pull "$POSTGRES_IMAGE" >/dev/null
POSTGRES_IMAGE_ID="$(docker image inspect "$POSTGRES_IMAGE" --format '{{.Id}}')"
[[ "$POSTGRES_IMAGE_ID" == sha256:* ]]
POSTGRES_REPO_DIGEST="$(
  docker image inspect "$POSTGRES_IMAGE" --format '{{index .RepoDigests 0}}' 2>/dev/null || true
)"
printf 'PostgreSQL acceptance image: id=%s digest=%s\n' \
  "$POSTGRES_IMAGE_ID" "${POSTGRES_REPO_DIGEST:-unavailable}"

start_postgres_container "$POSTGRES_IMAGE_ID"
wait_for_postgres

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

EXPECTED_HEAD_REVISION="$(run_alembic heads | awk 'NF {print $1}' | tail -n 1 | tr -d '\r')"
[[ -n "$EXPECTED_HEAD_REVISION" ]]

run_alembic upgrade head >/dev/null
UPGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$UPGRADED_REVISION" == *"$EXPECTED_HEAD_REVISION"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NOT NULL AND to_regclass('public.security_local_sessions') IS NOT NULL;")" == "t" ]]

run_alembic downgrade 20260731_0021 >/dev/null
DOWNGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$DOWNGRADED_REVISION" == *"20260731_0021"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NULL AND to_regclass('public.security_local_sessions') IS NULL;")" == "t" ]]

run_alembic upgrade head >/dev/null
REUPGRADED_REVISION="$(run_alembic current | tr -d '\r')"
[[ "$REUPGRADED_REVISION" == *"$EXPECTED_HEAD_REVISION"* ]]
[[ "$(query_database "SELECT to_regclass('public.security_local_accounts') IS NOT NULL AND to_regclass('public.security_local_sessions') IS NOT NULL;")" == "t" ]]

cat >"$EVIDENCE_DIR/migration-roundtrip.txt" <<EOF
expected_head_revision=$EXPECTED_HEAD_REVISION
upgrade_revision=$UPGRADED_REVISION
downgrade_revision=$DOWNGRADED_REVISION
reupgrade_revision=$REUPGRADED_REVISION
postgres_image_id=$POSTGRES_IMAGE_ID
postgres_repo_digest=${POSTGRES_REPO_DIGEST:-unavailable}
local_auth_tables_after_upgrade=present
local_auth_tables_after_downgrade=absent
local_auth_tables_after_reupgrade=present
status=passed
EOF

printf 'Local-auth migration round-trip passed. Evidence: %s\n' "$EVIDENCE_DIR"
