#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/deployments/repair-postgres-password-$STAMP"
CENTRAL_DIR="$REPO/infrastructure/compose"
CENTRAL_ENV="$CENTRAL_DIR/.env.central"
CENTRAL_COMPOSE="$CENTRAL_DIR/compose.central.yaml"
OBS_COMPOSE="$CENTRAL_DIR/compose.observability.yaml"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/repair.log") 2>&1

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

on_error() {
  local rc=$?
  log "POSTGRES PASSWORD REPAIR FAILED with exit code $rc"
  docker compose --env-file "$CENTRAL_ENV" \
    -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" ps -a \
    > "$EVIDENCE_DIR/central-ps.txt" 2>&1 || true
  docker compose --env-file "$CENTRAL_ENV" \
    -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
    logs --tail=160 --no-color postgres telemetry-migrate telemetry-service \
    > "$EVIDENCE_DIR/central-logs.txt" 2>&1 || true
  log "Evidence: $EVIDENCE_DIR"
  exit "$rc"
}
trap on_error ERR

cd "$REPO"
[[ -f "$CENTRAL_ENV" ]] || { echo "Missing $CENTRAL_ENV" >&2; exit 1; }
chmod 0600 "$CENTRAL_ENV"

for key in POSTGRES_USER POSTGRES_DB POSTGRES_PASSWORD; do
  grep -qE "^${key}=.+" "$CENTRAL_ENV" || {
    echo "Missing or empty $key in $CENTRAL_ENV" >&2
    exit 1
  }
done

log "Capturing configuration checksum without exposing secrets"
sha256sum "$CENTRAL_ENV" > "$EVIDENCE_DIR/env-central.sha256"

log "Recreating only PostgreSQL container with current environment; volume is preserved"
docker compose --env-file "$CENTRAL_ENV" \
  -f "$CENTRAL_COMPOSE" -f "$OBS_COMPOSE" \
  up -d --force-recreate postgres

for attempt in $(seq 1 60); do
  if docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_COMPOSE" \
    exec -T postgres sh -ec 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    >/dev/null 2>&1; then
    log "PostgreSQL is ready"
    break
  fi
  if [[ "$attempt" == "60" ]]; then
    echo "PostgreSQL readiness timeout" >&2
    exit 1
  fi
  sleep 2
done

log "Synchronizing existing database role password with current .env.central"
docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_COMPOSE" \
  exec -T postgres sh -ec '
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'"'"'SQL'"'"'
\getenv role_name POSTGRES_USER
\getenv new_password POSTGRES_PASSWORD
ALTER ROLE :"role_name" WITH LOGIN PASSWORD :'"'"'new_password'"'"';
SQL
  '

log "Verifying SCRAM password authentication over TCP"
docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_COMPOSE" \
  exec -T postgres sh -ec '
    PGPASSWORD="$POSTGRES_PASSWORD" \
      psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -v ON_ERROR_STOP=1 -Atc "SELECT 1;"
  ' | tee "$EVIDENCE_DIR/password-auth-check.txt"

grep -qx '1' "$EVIDENCE_DIR/password-auth-check.txt" || {
  echo "TCP password verification did not return 1" >&2
  exit 1
}

log "Reading current Alembic revision through local socket"
docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_COMPOSE" \
  exec -T postgres sh -ec '
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc \
      "SELECT version_num FROM alembic_version;"
  ' | tee "$EVIDENCE_DIR/alembic-before.txt"

cat > "$EVIDENCE_DIR/manifest.txt" <<EOF
status=passed
completed_at=$(date --iso-8601=seconds)
commit=$(git rev-parse HEAD)
operation=postgres-role-password-synchronized
volume_deleted=false
env_checksum=$(cut -d' ' -f1 "$EVIDENCE_DIR/env-central.sha256")
evidence=$EVIDENCE_DIR
EOF

log "POSTGRES ROLE PASSWORD REPAIR PASSED"
echo "Evidence: $EVIDENCE_DIR"
