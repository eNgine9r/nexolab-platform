#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"
BROWSER_COMPOSE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery-browser.yaml"
FIXTURES_SQL="$ROOT_DIR/scripts/disaster-recovery-domain-fixtures.sql"
PROJECT_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
PROJECT_NAME="nexolab-dr-browser-${PROJECT_SUFFIX}"
PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${PROJECT_NAME}.XXXXXX")"
SECRETS_DIR="$PRIVATE_DIR/secrets"
WORK_DIR="$PRIVATE_DIR/work"
EVIDENCE_DIR="$ROOT_DIR/test-results-disaster-recovery-browser"
DATABASE_DUMP="$WORK_DIR/nexolab-browser.dump"
OBJECT_BACKUP="$WORK_DIR/object-backup"
IMAGE_FILE="$WORK_DIR/dr-restored-showcase.png"
BUCKET="nexolab-equipment-images"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000099"
EQUIPMENT_ID="showcase-106-01"
OBJECT_KEY="equipment/showcase-106-01/dr-restored-showcase.png"
API_PORT="${DR_BROWSER_API_PORT:-8098}"
MINIO_PORT="${DR_BROWSER_MINIO_PORT:-9014}"
FRONTEND_PORT="${DR_BROWSER_FRONTEND_PORT:-3114}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"
FRONTEND_LOG="$EVIDENCE_DIR/frontend.log"
FRONTEND_PID=""
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
export DR_BROWSER_ORGANIZATION_ID="$ORGANIZATION_ID"
export DR_BROWSER_API_PORT="$API_PORT"
export DR_BROWSER_MINIO_PORT="$MINIO_PORT"
export DR_BROWSER_FRONTEND_PORT="$FRONTEND_PORT"
export DR_NETWORK="${PROJECT_NAME}-network"
export DR_SOURCE_POSTGRES_VOLUME="${PROJECT_NAME}-source-postgres"
export DR_RESTORE_POSTGRES_VOLUME="${PROJECT_NAME}-restore-postgres"
export DR_SOURCE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-source-object-storage"
export DR_RESTORE_OBJECT_STORAGE_VOLUME="${PROJECT_NAME}-restore-object-storage"
export DR_SOURCE_MQTT_VOLUME="${PROJECT_NAME}-source-mqtt"
export DR_RESTORE_MQTT_VOLUME="${PROJECT_NAME}-restore-mqtt"
export DR_TELEMETRY_IMAGE="nexolab-telemetry-service:dr-browser-${PROJECT_SUFFIX}"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    -f "$BASE_COMPOSE" \
    -f "$BROWSER_COMPOSE" \
    "$@"
}

wait_for_url() {
  local url=$1
  local label=$2
  for _ in $(seq 1 240); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

cleanup() {
  local status=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color \
    source-postgres source-minio restore-postgres restore-minio \
    restore-telemetry-service \
    >"$EVIDENCE_DIR/services.log" 2>&1 || true
  compose down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm \
    "$DR_SOURCE_POSTGRES_VOLUME" "$DR_RESTORE_POSTGRES_VOLUME" \
    "$DR_SOURCE_OBJECT_STORAGE_VOLUME" "$DR_RESTORE_OBJECT_STORAGE_VOLUME" \
    >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Restored operator browser acceptance failed." >&2
    tail -n 160 "$FRONTEND_LOG" >&2 || true
    tail -n 220 "$EVIDENCE_DIR/services.log" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in curl docker git npm python3 sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

rm -rf "$EVIDENCE_DIR"
mkdir -p "$SECRETS_DIR" "$WORK_DIR" "$OBJECT_BACKUP" "$EVIDENCE_DIR"
chmod 0700 "$PRIVATE_DIR" "$WORK_DIR"
chmod 0755 "$SECRETS_DIR"
printf '%s' "$(random_secret)" >"$SECRETS_DIR/admin-password"
chmod 0444 "$SECRETS_DIR/admin-password"

python3 - "$IMAGE_FILE" <<'PY'
from pathlib import Path
import base64
import sys

png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
Path(sys.argv[1]).write_bytes(png)
PY
IMAGE_SHA="$(sha256sum "$IMAGE_FILE" | awk '{print $1}')"
IMAGE_BYTES="$(stat -c '%s' "$IMAGE_FILE")"

compose config --quiet
compose build source-migrate restore-migrate restore-telemetry-service
compose up -d --wait source-postgres source-minio restore-postgres restore-minio
compose run --rm source-migrate

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES ('$ORGANIZATION_ID', 'nexolab-dr-browser', 'NEXOLAB DR Browser', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;
SQL

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <"$FIXTURES_SQL"

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  -v ON_ERROR_STOP=1 <<SQL
UPDATE equipment_images
SET equipment_id = '$EQUIPMENT_ID',
    storage_key = '$OBJECT_KEY',
    original_filename = 'dr-restored-showcase.png',
    media_type = 'image/png',
    size_bytes = $IMAGE_BYTES,
    width_px = 1,
    height_px = 1,
    checksum_sha256 = '$IMAGE_SHA',
    object_etag = '$IMAGE_SHA'
WHERE id = '80000000-0000-0000-0000-000000000099';

UPDATE refrigeration_layout_drafts
SET equipment_id = '$EQUIPMENT_ID',
    placements = '[{"sensor_id":"sensor-1","x":0.25,"y":0.35},{"sensor_id":"sensor-2","x":0.75,"y":0.65}]'::jsonb
WHERE id = '81000000-0000-0000-0000-000000000099';

INSERT INTO refrigeration_layout_revisions (
  id, organization_id, equipment_id, revision, source_draft_version,
  image_id, placements, published_by, published_at
) VALUES (
  '82000000-0000-0000-0000-000000000098',
  '$ORGANIZATION_ID',
  '$EQUIPMENT_ID',
  1,
  1,
  '80000000-0000-0000-0000-000000000099',
  '[{"sensor_id":"sensor-1","x":0.25,"y":0.35},{"sensor_id":"sensor-2","x":0.75,"y":0.65}]'::jsonb,
  'dr-browser-operator',
  '2026-07-28T06:54:00Z'
);
SQL

compose run --rm minio-client "
  mc alias set source http://source-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mb --ignore-existing source/$BUCKET >/dev/null
  mc cp --attr 'Content-Type=image/png' /work/dr-restored-showcase.png source/$BUCKET/$OBJECT_KEY >/dev/null
  mc anonymous set none source/$BUCKET >/dev/null
  rm -rf /work/object-backup
  mkdir -p /work/object-backup
  mc mirror source/$BUCKET /work/object-backup >/dev/null
"

test -s "$OBJECT_BACKUP/$OBJECT_KEY"
test "$IMAGE_SHA" = "$(sha256sum "$OBJECT_BACKUP/$OBJECT_KEY" | awk '{print $1}')"

compose exec -T source-postgres \
  pg_dump -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" --format=custom \
  >"$DATABASE_DUMP"
test -s "$DATABASE_DUMP"

compose exec -T restore-postgres \
  pg_restore -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" \
  --clean --if-exists <"$DATABASE_DUMP"
compose run --rm restore-migrate

compose run --rm minio-client "
  mc alias set restore http://restore-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mb --ignore-existing restore/$BUCKET >/dev/null
  mc mirror --overwrite /work/object-backup restore/$BUCKET >/dev/null
  mc anonymous set none restore/$BUCKET >/dev/null
"

compose up -d --wait restore-telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "restored telemetry API"

curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer disaster-recovery-browser-acceptance" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  "$API_BASE_URL/api/v1/nodes" >"$EVIDENCE_DIR/nodes-api.json"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer disaster-recovery-browser-acceptance" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  "$API_BASE_URL/api/v1/reports?limit=20" >"$EVIDENCE_DIR/reports-api.json"
curl --fail-with-body --silent --show-error \
  -H "Authorization: Bearer disaster-recovery-browser-acceptance" \
  -H "X-Organization-ID: $ORGANIZATION_ID" \
  "$API_BASE_URL/api/v1/equipment/$EQUIPMENT_ID/layout/draft" \
  >"$EVIDENCE_DIR/refrigeration-draft-api.json"

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_ID"
export NEXT_PUBLIC_NEXOLAB_OPERATOR_ID="disaster-recovery-browser"
export NEXT_TELEMETRY_DISABLED="1"
export NEXOLAB_DR_BROWSER_BASE_URL="$FRONTEND_BASE_URL"
export NEXOLAB_DR_BROWSER_API_BASE_URL="$API_BASE_URL"
export NEXOLAB_DR_BROWSER_ORGANIZATION_ID="$ORGANIZATION_ID"
export NEXOLAB_DR_BROWSER_EVIDENCE_DIR="$EVIDENCE_DIR"

npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/nodes" "restored Next.js operator UI"

npx playwright test --config=playwright.disaster-recovery.config.ts

DATABASE_ROWS="$(compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
  "SELECT jsonb_build_object(
    'nodes', (SELECT count(*) FROM central_nodes WHERE organization_id = '$ORGANIZATION_ID'),
    'reports', (SELECT count(*) FROM test_report_versions WHERE organization_id = '$ORGANIZATION_ID'),
    'report_artifacts', (SELECT count(*) FROM test_report_artifacts WHERE report_id = '60000000-0000-0000-0000-000000000099'),
    'drafts', (SELECT count(*) FROM refrigeration_layout_drafts WHERE equipment_id = '$EQUIPMENT_ID'),
    'revisions', (SELECT count(*) FROM refrigeration_layout_revisions WHERE equipment_id = '$EQUIPMENT_ID'),
    'images', (SELECT count(*) FROM equipment_images WHERE equipment_id = '$EQUIPMENT_ID')
  )")"

python3 - "$DATABASE_ROWS" "$EVIDENCE_DIR/database-counts.json" <<'PY'
from pathlib import Path
import json
import sys

payload = json.loads(sys.argv[1])
expected = {
    "nodes": 2,
    "reports": 1,
    "report_artifacts": 1,
    "drafts": 1,
    "revisions": 1,
    "images": 1,
}
if payload != expected:
    raise SystemExit(f"Restored browser database counts do not match: {payload!r}")
Path(sys.argv[2]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

RESTORED_IMAGE="$WORK_DIR/restored-image.png"
compose run --rm minio-client "
  mc alias set restore http://restore-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc cp restore/$BUCKET/$OBJECT_KEY /work/restored-image.png >/dev/null
"
test "$IMAGE_SHA" = "$(sha256sum "$RESTORED_IMAGE" | awk '{print $1}')"

SOURCE_COMMIT="${GITHUB_SHA:-}"
if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi
DURATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
DUMP_BYTES="$(stat -c '%s' "$DATABASE_DUMP")"

python3 - "$EVIDENCE_DIR/summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "repository": "eNgine9r/nexolab-platform",
    "commit": "$SOURCE_COMMIT",
    "duration_seconds": $DURATION_SECONDS,
    "database_dump_bytes": int("$DUMP_BYTES"),
    "restored_image_sha256": "$IMAGE_SHA",
    "routes": {
        "/nodes": "chromium_passed",
        "/reports": "chromium_passed",
        "/refrigeration/showcase-106-01": "chromium_passed",
    },
    "fresh_restore_volumes": True,
    "source_volumes_mutated": False,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 - "$EVIDENCE_DIR" "$SECRETS_DIR" <<'PY'
from pathlib import Path
import sys

evidence = Path(sys.argv[1])
secrets = [path.read_bytes() for path in Path(sys.argv[2]).iterdir() if path.is_file()]
for artifact in evidence.rglob("*"):
    if not artifact.is_file():
        continue
    content = artifact.read_bytes()
    for secret in secrets:
        if secret and secret in content:
            raise SystemExit(f"Secret material leaked into browser evidence: {artifact}")
PY

python3 -m json.tool "$EVIDENCE_DIR/summary.json"
echo "Restored operator browser acceptance passed."
