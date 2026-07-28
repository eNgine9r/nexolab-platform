#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.disaster-recovery.yaml"
POLICY_FILE="$ROOT_DIR/security/disaster-recovery-assets.json"
BUNDLE_TOOL="$ROOT_DIR/scripts/nexolab-backup-bundle.py"
PROJECT_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
PROJECT_NAME="nexolab-dr-${PROJECT_SUFFIX}"
PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/${PROJECT_NAME}.XXXXXX")"
SECRETS_DIR="$PRIVATE_DIR/secrets"
WORK_DIR="$PRIVATE_DIR/work"
PAYLOAD_DIR="$WORK_DIR/payload"
RESTORED_DIR="$WORK_DIR/restored"
EVIDENCE_DIR="$ROOT_DIR/test-results-disaster-recovery"
BUNDLE_FILE="$WORK_DIR/nexolab-backup.nxl"
KEY_FILE="$PRIVATE_DIR/backup-key"
WRONG_KEY_FILE="$PRIVATE_DIR/wrong-backup-key"
TAMPERED_BUNDLE="$WORK_DIR/nexolab-backup-tampered.nxl"
BUCKET="nexolab-equipment-images"
REPOSITORY="eNgine9r/nexolab-platform"
SOURCE_COMMIT="${GITHUB_SHA:-}"

if [[ ! "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  SOURCE_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"
fi

mkdir -p "$SECRETS_DIR" "$WORK_DIR" "$PAYLOAD_DIR" "$EVIDENCE_DIR"
rm -rf "$EVIDENCE_DIR"/*
chmod 0700 "$PRIVATE_DIR" "$SECRETS_DIR" "$WORK_DIR"

random_secret() {
  python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(36))
PY
}

write_secret() {
  local path=$1
  python3 - "$path" <<'PY'
from pathlib import Path
import secrets
import sys
path = Path(sys.argv[1])
path.write_text(secrets.token_urlsafe(36), encoding="utf-8")
path.chmod(0o400)
PY
}

write_raw_key() {
  local path=$1
  python3 - "$path" <<'PY'
from pathlib import Path
import secrets
import sys
path = Path(sys.argv[1])
path.write_bytes(secrets.token_bytes(32))
path.chmod(0o600)
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
export DR_TELEMETRY_IMAGE="nexolab-telemetry-service:disaster-recovery-${PROJECT_SUFFIX}"
export DR_MQTT_IMAGE="nexolab-mqtt-dynamic-security:disaster-recovery-${PROJECT_SUFFIX}"

write_secret "$SECRETS_DIR/admin-password"
write_secret "$SECRETS_DIR/ingestion-password"
write_secret "$SECRETS_DIR/edge-01-old-password"
write_secret "$SECRETS_DIR/edge-01-password"
write_secret "$SECRETS_DIR/edge-02-password"
write_raw_key "$KEY_FILE"
write_raw_key "$WRONG_KEY_FILE"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color \
    source-postgres restore-postgres source-minio restore-minio \
    source-mqtt restore-mqtt >"$EVIDENCE_DIR/services.log" 2>&1 || true
  compose down --remove-orphans >/dev/null 2>&1 || true
  docker volume rm \
    "$DR_SOURCE_POSTGRES_VOLUME" "$DR_RESTORE_POSTGRES_VOLUME" \
    "$DR_SOURCE_OBJECT_STORAGE_VOLUME" "$DR_RESTORE_OBJECT_STORAGE_VOLUME" \
    "$DR_SOURCE_MQTT_VOLUME" "$DR_RESTORE_MQTT_VOLUME" \
    >/dev/null 2>&1 || true
  rm -rf "$PRIVATE_DIR"
  if [[ $status -ne 0 ]]; then
    echo "Disaster-recovery acceptance failed." >&2
    tail -n 240 "$EVIDENCE_DIR/services.log" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

for command in docker python3 git sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is missing: $command" >&2
    exit 1
  }
done

docker compose version >/dev/null
python3 "$ROOT_DIR/scripts/validate-disaster-recovery-assets.py" --policy "$POLICY_FILE"
compose config --quiet

compose build source-migrate source-mqtt
compose up -d --wait source-postgres source-minio source-mqtt
compose run --rm source-migrate

compose exec -T source-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES ('00000000-0000-0000-0000-000000000001', 'nexolab-dr', 'NEXOLAB DR', true);

INSERT INTO security_audit_events (
  id, organization_id, actor_subject, actor_roles, action,
  entity_type, entity_id, after_snapshot, reason, request_id, source_ip, user_agent
) VALUES (
  '10000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000001',
  'dr-acceptance', '["administrator"]'::json, 'backup.seed',
  'disaster_recovery', 'nexolab-dr-v1', '{"immutable":true}'::json,
  'Seed encrypted recovery acceptance', 'dr-request-001', '127.0.0.1', 'nexolab-dr-acceptance'
);

INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload,
  raw_payload_retained
) VALUES
  (
    '20000000-0000-0000-0000-000000000001', 'edge-01',
    '2026-07-28T07:00:00Z', 'temperature', 3.7, 'degC', 'good', 'dr-acceptance',
    'SIM-DR-01', 'ambient-temperature', NULL, 37, 0,
    '{"sequence":1,"proof":"source"}'::json, true
  ),
  (
    '20000000-0000-0000-0000-000000000002', 'edge-02',
    '2026-07-28T07:00:01Z', 'temperature', 4.1, 'degC', 'good', 'dr-acceptance',
    'SIM-DR-02', 'ambient-temperature', NULL, 41, 0,
    '{"sequence":1,"proof":"source"}'::json, true
  );
SQL

mkdir -p "$WORK_DIR/seed-objects/equipment" "$WORK_DIR/seed-objects/reports/session-001"
printf '%s\n' 'NEXOLAB equipment image recovery fixture' >"$WORK_DIR/seed-objects/equipment/fixture-a.bin"
printf '%s\n' '{"report":"immutable","version":1}' >"$WORK_DIR/seed-objects/reports/session-001/report.json"
python3 - "$WORK_DIR/seed-objects/equipment/fixture-b.bin" <<'PY'
from pathlib import Path
import hashlib
import sys
seed = b"nexolab-disaster-recovery-object-v1"
Path(sys.argv[1]).write_bytes(hashlib.sha256(seed).digest() * 64)
PY

compose run --rm minio-client "
  mc alias set source http://source-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mb --ignore-existing source/$BUCKET >/dev/null
  mc anonymous set none source/$BUCKET >/dev/null
  mc mirror --overwrite /work/seed-objects source/$BUCKET >/dev/null
"

ORGANIZATION_ID="00000000-0000-0000-0000-000000000001"
EDGE_01_USERNAME="node:${ORGANIZATION_ID}:edge-01"
EDGE_02_USERNAME="node:${ORGANIZATION_ID}:edge-02"
EDGE_01_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-01"
EDGE_02_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-02"

compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin bootstrap-defaults
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-ingestion nexolab-central-ingestion nexolab-central-ingestion \
  /run/secrets/nexolab/ingestion-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-node "$EDGE_01_USERNAME" "$EDGE_01_CLIENT_ID" "$ORGANIZATION_ID" edge-01 \
  /run/secrets/nexolab/edge-01-old-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  rotate-password "$EDGE_01_USERNAME" /run/secrets/nexolab/edge-01-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  create-node "$EDGE_02_USERNAME" "$EDGE_02_CLIENT_ID" "$ORGANIZATION_ID" edge-02 \
  /run/secrets/nexolab/edge-02-password
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin \
  disable-client "$EDGE_02_USERNAME"

capture_database_state() {
  local service=$1
  local output=$2
  compose exec -T "$service" \
    psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -At -v ON_ERROR_STOP=1 \
    >"$output" <<'SQL'
SELECT jsonb_build_object(
  'organizations', COALESCE((
    SELECT jsonb_agg(jsonb_build_object('id', id, 'slug', slug, 'name', name, 'active', is_active) ORDER BY id)
    FROM security_organizations
  ), '[]'::jsonb),
  'audit', COALESCE((
    SELECT jsonb_agg(jsonb_build_object('id', id, 'action', action, 'entity_type', entity_type, 'entity_id', entity_id, 'after', after_snapshot) ORDER BY id)
    FROM security_audit_events
  ), '[]'::jsonb),
  'telemetry', COALESCE((
    SELECT jsonb_agg(jsonb_build_object('event_id', event_id, 'node_id', node_id, 'captured_at', captured_at, 'metric', metric, 'value', value, 'unit', unit, 'quality', quality, 'equipment_id', equipment_id, 'channel_id', channel_id, 'raw_payload', raw_payload) ORDER BY event_id)
    FROM telemetry_samples
  ), '[]'::jsonb),
  'alembic_head', COALESCE((SELECT jsonb_agg(version_num ORDER BY version_num) FROM alembic_version), '[]'::jsonb)
)::text;
SQL
}

capture_mqtt_state() {
  local service=$1
  local output=$2
  {
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin list-clients | sort
    printf '%s\n' '--- edge-01 ---'
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin get-client "$EDGE_01_USERNAME"
    printf '%s\n' '--- edge-02 ---'
    compose exec -T "$service" /usr/local/bin/nexolab-dynsec-admin get-client "$EDGE_02_USERNAME"
  } >"$output"
}

capture_database_state source-postgres "$WORK_DIR/source-database-state.json"
capture_mqtt_state source-mqtt "$WORK_DIR/source-mqtt-state.txt"
SOURCE_DATABASE_SHA="$(sha256sum "$WORK_DIR/source-database-state.json" | awk '{print $1}')"
SOURCE_MQTT_SHA="$(sha256sum "$WORK_DIR/source-mqtt-state.txt" | awk '{print $1}')"

BACKUP_STARTED="$(date +%s)"
mkdir -p "$PAYLOAD_DIR/postgresql" "$PAYLOAD_DIR/object-storage" "$PAYLOAD_DIR/mqtt"
compose exec -T source-postgres \
  pg_dump -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Fc \
  >"$PAYLOAD_DIR/postgresql/nexolab.dump"
test -s "$PAYLOAD_DIR/postgresql/nexolab.dump"

compose run --rm minio-client "
  rm -rf /work/payload/object-storage/objects
  mkdir -p /work/payload/object-storage/objects
  mc alias set source http://source-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mirror source/$BUCKET /work/payload/object-storage/objects >/dev/null
"
find "$PAYLOAD_DIR/object-storage/objects" -type f -printf '%P\n' | LC_ALL=C sort \
  >"$WORK_DIR/object-keys.txt"
test -s "$WORK_DIR/object-keys.txt"
compose run --rm minio-client "
  mc alias set source http://source-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  : > /work/source-object-stats.ndjson
  while IFS= read -r key; do
    mc stat --json \"source/$BUCKET/\$key\" >> /work/source-object-stats.ndjson
  done < /work/object-keys.txt
"
python3 - "$PAYLOAD_DIR/object-storage/objects" "$WORK_DIR/object-keys.txt" \
  "$WORK_DIR/source-object-stats.ndjson" "$PAYLOAD_DIR/object-storage/objects.json" <<'PY'
from pathlib import Path
import hashlib
import json
import sys
root, keys_path, stats_path, output_path = map(Path, sys.argv[1:])
keys = keys_path.read_text(encoding="utf-8").splitlines()
stats = [json.loads(line) for line in stats_path.read_text(encoding="utf-8").splitlines() if line]
if len(keys) != len(stats):
    raise SystemExit("MinIO stat count does not match exported object count")
objects = []
for key, stat in zip(keys, stats, strict=True):
    path = root / key
    content = path.read_bytes()
    size = stat.get("size")
    etag = stat.get("etag") or stat.get("ETag")
    if size != len(content) or not isinstance(etag, str) or not etag:
        raise SystemExit(f"MinIO metadata is incomplete for {key}")
    objects.append({
        "key": key,
        "size": size,
        "etag": etag.strip('"'),
        "sha256": hashlib.sha256(content).hexdigest(),
    })
payload = {"schema_version": 1, "bucket": "nexolab-equipment-images", "objects": objects}
output_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
PY
SOURCE_OBJECTS_SHA="$(sha256sum "$PAYLOAD_DIR/object-storage/objects.json" | awk '{print $1}')"

compose stop source-mqtt
compose run --rm volume-helper \
  "python /opt/nexolab/scripts/nexolab-volume-archive.py create --source /source-mqtt --output /work/payload/mqtt/mosquitto-data.tar"
test -s "$PAYLOAD_DIR/mqtt/mosquitto-data.tar"
compose start source-mqtt
for _ in $(seq 1 60); do
  if compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin list-clients >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
compose exec -T source-mqtt /usr/local/bin/nexolab-dynsec-admin list-clients >/dev/null

python3 "$BUNDLE_TOOL" --policy "$POLICY_FILE" create \
  --payload-dir "$PAYLOAD_DIR" \
  --key-file "$KEY_FILE" \
  --output "$BUNDLE_FILE" \
  --repository "$REPOSITORY" \
  --commit "$SOURCE_COMMIT" \
  >"$EVIDENCE_DIR/bundle-create.json"
python3 "$BUNDLE_TOOL" --policy "$POLICY_FILE" verify \
  --bundle "$BUNDLE_FILE" --key-file "$KEY_FILE" \
  >"$EVIDENCE_DIR/bundle-verify.json"

if python3 "$BUNDLE_TOOL" --policy "$POLICY_FILE" verify \
  --bundle "$BUNDLE_FILE" --key-file "$WRONG_KEY_FILE" \
  >"$WORK_DIR/wrong-key.log" 2>&1; then
  echo "Wrong backup key was accepted." >&2
  exit 80
fi
python3 - "$BUNDLE_FILE" "$TAMPERED_BUNDLE" <<'PY'
from pathlib import Path
import sys
source = bytearray(Path(sys.argv[1]).read_bytes())
source[-1] ^= 0x01
Path(sys.argv[2]).write_bytes(source)
PY
if python3 "$BUNDLE_TOOL" --policy "$POLICY_FILE" verify \
  --bundle "$TAMPERED_BUNDLE" --key-file "$KEY_FILE" \
  >"$WORK_DIR/tamper.log" 2>&1; then
  echo "Modified ciphertext was accepted." >&2
  exit 81
fi
BACKUP_SECONDS="$(( $(date +%s) - BACKUP_STARTED ))"

RESTORE_STARTED="$(date +%s)"
python3 "$BUNDLE_TOOL" --policy "$POLICY_FILE" extract \
  --bundle "$BUNDLE_FILE" --key-file "$KEY_FILE" --output-dir "$RESTORED_DIR" \
  >"$EVIDENCE_DIR/bundle-extract.json"

compose up -d --wait restore-postgres restore-minio
compose exec -T restore-postgres \
  pg_restore -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" --clean --if-exists \
  <"$RESTORED_DIR/postgresql/nexolab.dump"

compose run --rm minio-client "
  mc alias set restore http://restore-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mb --ignore-existing restore/$BUCKET >/dev/null
  mc mirror --overwrite /work/restored/object-storage/objects restore/$BUCKET >/dev/null
  mc anonymous set none restore/$BUCKET >/dev/null
  mc anonymous get restore/$BUCKET > /work/restore-bucket-policy.txt
"

test ! -e "$WORK_DIR/restore-mqtt-sentinel"
compose run --rm volume-helper \
  "python /opt/nexolab/scripts/nexolab-volume-archive.py extract --archive /work/restored/mqtt/mosquitto-data.tar --destination /restore-mqtt"
compose up -d --wait restore-mqtt

capture_database_state restore-postgres "$WORK_DIR/restore-database-state.json"
capture_mqtt_state restore-mqtt "$WORK_DIR/restore-mqtt-state.txt"
RESTORE_DATABASE_SHA="$(sha256sum "$WORK_DIR/restore-database-state.json" | awk '{print $1}')"
RESTORE_MQTT_SHA="$(sha256sum "$WORK_DIR/restore-mqtt-state.txt" | awk '{print $1}')"
test "$SOURCE_DATABASE_SHA" = "$RESTORE_DATABASE_SHA"
test "$SOURCE_MQTT_SHA" = "$RESTORE_MQTT_SHA"
grep -Fqi 'private' "$WORK_DIR/restore-bucket-policy.txt"

compose run --rm minio-client "
  rm -rf /work/restore-objects
  mkdir -p /work/restore-objects
  mc alias set restore http://restore-minio:9000 \"\$MINIO_ROOT_USER\" \"\$MINIO_ROOT_PASSWORD\" >/dev/null
  mc mirror restore/$BUCKET /work/restore-objects >/dev/null
"
python3 - "$PAYLOAD_DIR/object-storage/objects" "$WORK_DIR/restore-objects" <<'PY'
from pathlib import Path
import hashlib
import sys

def tree(root: Path) -> list[tuple[str, int, str]]:
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        content = path.read_bytes()
        result.append((path.relative_to(root).as_posix(), len(content), hashlib.sha256(content).hexdigest()))
    return result

source = tree(Path(sys.argv[1]))
restored = tree(Path(sys.argv[2]))
if source != restored or not source:
    raise SystemExit("Restored MinIO object tree does not match source")
PY

capture_database_state source-postgres "$WORK_DIR/source-database-state-after.json"
capture_mqtt_state source-mqtt "$WORK_DIR/source-mqtt-state-after.txt"
test "$SOURCE_DATABASE_SHA" = "$(sha256sum "$WORK_DIR/source-database-state-after.json" | awk '{print $1}')"
test "$SOURCE_MQTT_SHA" = "$(sha256sum "$WORK_DIR/source-mqtt-state-after.txt" | awk '{print $1}')"

RESTORE_SECONDS="$(( $(date +%s) - RESTORE_STARTED ))"
BUNDLE_SIZE="$(stat -c '%s' "$BUNDLE_FILE")"
DATABASE_ROWS="$(compose exec -T restore-postgres psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc "SELECT COUNT(*) FROM telemetry_samples")"
OBJECT_COUNT="$(find "$WORK_DIR/restore-objects" -type f | wc -l | tr -d ' ')"
MQTT_CLIENT_COUNT="$(compose exec -T restore-mqtt /usr/local/bin/nexolab-dynsec-admin list-clients | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"

grep -Fq 'Disabled: true' "$WORK_DIR/restore-mqtt-state.txt"
cp "$BUNDLE_FILE" "$EVIDENCE_DIR/nexolab-backup.nxl"
printf '%s\n' \
  'wrong_key=rejected' \
  'ciphertext_tamper=rejected' \
  'source_volumes=unchanged_during_drill' \
  'restore_volumes=fresh' \
  'object_storage=private' \
  >"$EVIDENCE_DIR/negative-and-safety-checks.txt"
printf '%s\n' "$SOURCE_DATABASE_SHA" >"$EVIDENCE_DIR/database-state.sha256"
printf '%s\n' "$SOURCE_OBJECTS_SHA" >"$EVIDENCE_DIR/object-manifest.sha256"
printf '%s\n' "$SOURCE_MQTT_SHA" >"$EVIDENCE_DIR/mqtt-policy-state.sha256"
cp "$WORK_DIR/restore-bucket-policy.txt" "$EVIDENCE_DIR/restore-bucket-policy.txt"

python3 - "$EVIDENCE_DIR/summary.json" <<PY
from pathlib import Path
import json
import sys
payload = {
    "schema_version": 1,
    "repository": "$REPOSITORY",
    "commit": "$SOURCE_COMMIT",
    "backup_seconds": $BACKUP_SECONDS,
    "restore_seconds": $RESTORE_SECONDS,
    "software_rpo_seconds": 0,
    "bundle_bytes": $BUNDLE_SIZE,
    "database": {"telemetry_rows": int("$DATABASE_ROWS"), "state_sha256": "$SOURCE_DATABASE_SHA"},
    "object_storage": {"bucket": "$BUCKET", "object_count": int("$OBJECT_COUNT"), "manifest_sha256": "$SOURCE_OBJECTS_SHA", "private": True},
    "mqtt": {"client_count": int("$MQTT_CLIENT_COUNT"), "state_sha256": "$SOURCE_MQTT_SHA", "disabled_client_restored": True},
    "negative_tests": {"wrong_key": "rejected", "ciphertext_tamper": "rejected"},
    "source_volumes_mutated": False,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

python3 - "$EVIDENCE_DIR" "$SECRETS_DIR" "$KEY_FILE" "$WRONG_KEY_FILE" <<'PY'
from pathlib import Path
import sys

evidence = Path(sys.argv[1])
secret_files = [*Path(sys.argv[2]).iterdir(), Path(sys.argv[3]), Path(sys.argv[4])]
secrets = [path.read_bytes() for path in secret_files]
for artifact in evidence.rglob("*"):
    if not artifact.is_file():
        continue
    content = artifact.read_bytes()
    for secret in secrets:
        if secret and secret in content:
            raise SystemExit(f"Secret material leaked into evidence: {artifact}")
print("Evidence leakage scan passed.")
PY

python3 -m json.tool "$EVIDENCE_DIR/summary.json"
echo "Disaster-recovery component acceptance passed."
