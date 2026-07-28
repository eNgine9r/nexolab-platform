#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"
FIXTURES_SQL="$ROOT_DIR/scripts/disaster-recovery-domain-fixtures.sql"
STATE_SQL="$ROOT_DIR/scripts/disaster-recovery-domain-state.sql"
COUNTS_SQL="$ROOT_DIR/scripts/disaster-recovery-domain-counts.sql"
PROJECT_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
PROJECT_NAME="nexolab-dr-domain-${PROJECT_SUFFIX}"
PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${PROJECT_NAME}.XXXXXX")"
SECRETS_DIR="$PRIVATE_DIR/secrets"
WORK_DIR="$PRIVATE_DIR/work"
EVIDENCE_DIR="$ROOT_DIR/test-results-disaster-recovery-domain"
DUMP_FILE="$WORK_DIR/nexolab-protected-domains.dump"
SOURCE_STATE="$WORK_DIR/source-protected-domain-state.json"
RESTORE_STATE="$WORK_DIR/restore-protected-domain-state.json"
STARTED_AT="$(date +%s)"

random_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
}

export DR_POSTGRES_DB="nexolab"
export DR_POSTGRES_USER="nexolab"
export DR_POSTGRES_PASSWORD="$(random_secret)"
export DR_MINIO_ROOT_USER="nexolabdr"
export DR_MINIO_ROOT_PASSWORD="$(random_secret)"
export DR_MQTT_ADMIN_USERNAME="nexolab-dr-admin"
export DR_SECRETS_DIR="$SECRETS_DIR"
export DR_WORK_DIR="$WORK_DIR"
export DR_NETWORK="${PROJECT_NAME}-network"
export DR_SOURCE_POSTGRES_VOLUME="${PROJECT_NAME}-source-postgres"
export DR_RESTORE_POSTGRES_VOLUME="${PROJECT_NAME}-restore-postgres"
export DR_SOURCE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-source-object-storage"
export DR_RESTORE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-restore-object-storage"
export DR_SOURCE_MQTT_VOLUME="${PROJECT_NAME}-source-mqtt"
export DR_RESTORE_MQTT_VOLUME="${PROJECT_NAME}-restore-mqtt"
export DR_TELEMETRY_IMAGE="nexolab-telemetry-service:dr-domain-${PROJECT_SUFFIX}"
export DR_MQTT_IMAGE="nexolab-mqtt-dynamic-security:dr-domain-${PROJECT_SUFFIX}"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color source-postgres restore-postgres \
    >"$EVIDENCE_DIR/services.log" 2>&1 || true
  compose down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm \
    "$DR_SOURCE_POSTGRES_VOLUME" "$DR_RESTORE_POSTGRES_VOLUME" \
    >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Protected-domain disaster-recovery acceptance failed." >&2
    tail -n 200 "$EVIDENCE_DIR/services.log" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in cmp docker git python3 sha256sum; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

rm -rf "$EVIDENCE_DIR"
mkdir -p "$SECRETS_DIR" "$WORK_DIR" "$EVIDENCE_DIR"
chmod 0700 "$PRIVATE_DIR" "$WORK_DIR"
chmod 0755 "$SECRETS_DIR"

compose config --quiet
compose build source-migrate
compose up -d --wait source-postgres restore-postgres
compose run --rm source-migrate

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES (
  '00000000-0000-0000-0000-000000000099',
  'nexolab-dr-domain',
  'NEXOLAB DR Domain Completeness',
  true
)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    is_active = true;
SQL

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <"$FIXTURES_SQL"

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <"$STATE_SQL" >"$SOURCE_STATE"
test -s "$SOURCE_STATE"

compose exec -T source-postgres \
  pg_dump -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" --format=custom \
  >"$DUMP_FILE"
test -s "$DUMP_FILE"

compose exec -T restore-postgres \
  pg_restore -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  --clean --if-exists <"$DUMP_FILE"

compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <"$STATE_SQL" >"$RESTORE_STATE"
test -s "$RESTORE_STATE"
cmp -s "$SOURCE_STATE" "$RESTORE_STATE"

SOURCE_SHA="$(sha256sum "$SOURCE_STATE" | awk '{print $1}')"
RESTORE_SHA="$(sha256sum "$RESTORE_STATE" | awk '{print $1}')"
test "$SOURCE_SHA" = "$RESTORE_SHA"

compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <"$COUNTS_SQL" \
  >"$EVIDENCE_DIR/protected-domain-counts.json"

python3 - "$EVIDENCE_DIR/protected-domain-counts.json" <<'PY'
from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
expected = {
    "sessions": 1,
    "session_config_snapshots": 1,
    "session_stages": 1,
    "alert_rules": 1,
    "alert_rule_versions": 1,
    "alert_instances": 1,
    "alert_transitions": 1,
    "report_versions": 1,
    "report_artifacts": 1,
    "nodes": 2,
    "node_credentials": 2,
    "broker_commands": 1,
    "equipment_images": 1,
    "refrigeration_drafts": 1,
    "refrigeration_revisions": 1,
}
if payload != expected:
    raise SystemExit(f"Protected-domain counts do not match: {payload!r}")
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

SOURCE_ALEMBIC="$(compose exec -T source-postgres psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc 'SELECT string_agg(version_num, '\''|'\'' ORDER BY version_num) FROM alembic_version')"
RESTORE_ALEMBIC="$(compose exec -T restore-postgres psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc 'SELECT string_agg(version_num, '\''|'\'' ORDER BY version_num) FROM alembic_version')"
test -n "$SOURCE_ALEMBIC"
test "$SOURCE_ALEMBIC" = "$RESTORE_ALEMBIC"

SOURCE_COMMIT="${GITHUB_SHA:-}"
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi
DURATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
DUMP_BYTES="$(stat -c '%s' "$DUMP_FILE")"

printf '%s\n' "$SOURCE_SHA" >"$EVIDENCE_DIR/protected-domain-state.sha256"
python3 - "$EVIDENCE_DIR/summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "repository": "eNgine9r/nexolab-platform",
    "commit": "$SOURCE_COMMIT",
    "duration_seconds": $DURATION_SECONDS,
    "dump_bytes": int("$DUMP_BYTES"),
    "source_state_sha256": "$SOURCE_SHA",
    "restore_state_sha256": "$RESTORE_SHA",
    "alembic_head": "$SOURCE_ALEMBIC",
    "fresh_restore_volume": True,
    "source_volume_mutated": False,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

python3 -m json.tool "$EVIDENCE_DIR/summary.json"
echo "Protected-domain disaster-recovery acceptance passed."
