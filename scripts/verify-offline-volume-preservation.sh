#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: verify-offline-volume-preservation.sh \
  --bundle-root PATH \
  --central-env PATH \
  --edge-env PATH \
  --evidence-dir PATH

Seeds service-level persistence markers, recreates the disconnected NEXOLAB
stack with update image tags, rolls back to the original tags, and proves that
all six required persistent-data volumes and markers survive both operations.
EOF
}

BUNDLE_ROOT=""
CENTRAL_ENV=""
EDGE_ENV=""
EVIDENCE_DIR=""
while (($#)); do
  case "$1" in
    --bundle-root) BUNDLE_ROOT="${2:?}"; shift 2 ;;
    --central-env) CENTRAL_ENV="${2:?}"; shift 2 ;;
    --edge-env) EDGE_ENV="${2:?}"; shift 2 ;;
    --evidence-dir) EVIDENCE_DIR="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -d "$BUNDLE_ROOT" ]] || { echo "Bundle root not found: $BUNDLE_ROOT" >&2; exit 2; }
[[ -f "$CENTRAL_ENV" ]] || { echo "Central environment file not found: $CENTRAL_ENV" >&2; exit 2; }
[[ -f "$EDGE_ENV" ]] || { echo "Edge environment file not found: $EDGE_ENV" >&2; exit 2; }
[[ -n "$EVIDENCE_DIR" ]] || { echo "--evidence-dir is required" >&2; exit 2; }
mkdir -p "$EVIDENCE_DIR"

for command in docker python3 cmp; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done

eval "$(python3 "$BUNDLE_ROOT/scripts/verify-offline-bundle.py" \
  "$BUNDLE_ROOT" --check-loaded-images --emit-shell-env)"
export OFFLINE_DASHBOARD_IMAGE OFFLINE_TELEMETRY_IMAGE OFFLINE_DEVICE_AGENT_IMAGE
export OFFLINE_MQTT_IMAGE OFFLINE_POSTGRES_IMAGE OFFLINE_MINIO_IMAGE OFFLINE_MINIO_CLIENT_IMAGE

CENTRAL=(docker compose --env-file "$CENTRAL_ENV" \
  -f "$BUNDLE_ROOT/deploy/compose/compose.central.yaml" \
  -f "$BUNDLE_ROOT/deploy/offline/compose.central.offline.yaml")
EDGE=(docker compose --env-file "$EDGE_ENV" \
  -f "$BUNDLE_ROOT/deploy/compose/compose.edge.yaml" \
  -f "$BUNDLE_ROOT/deploy/offline/compose.edge.offline.yaml")

volume_name_for_destination() {
  local container_id="$1"
  local destination="$2"
  [[ -n "$container_id" ]] || { echo "Missing container id for $destination" >&2; return 1; }
  docker inspect "$container_id" --format '{{json .Mounts}}' \
    | python3 -c '
import json
import sys

destination = sys.argv[1]
mounts = json.load(sys.stdin)
matches = [
    item["Name"]
    for item in mounts
    if item.get("Type") == "volume" and item.get("Destination") == destination
]
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one named volume at {destination}, found {len(matches)}: {mounts}"
    )
print(matches[0])
' "$destination"
}

central_volume() {
  local service="$1"
  local destination="$2"
  volume_name_for_destination "$("${CENTRAL[@]}" ps -q "$service")" "$destination"
}

edge_volume() {
  local service="$1"
  local destination="$2"
  volume_name_for_destination "$("${EDGE[@]}" ps -q "$service")" "$destination"
}

snapshot_required_volumes() {
  printf 'central_mqtt=%s\n' "$(central_volume mqtt /mosquitto/data)"
  printf 'central_postgres=%s\n' "$(central_volume postgres /var/lib/postgresql/data)"
  printf 'central_minio=%s\n' "$(central_volume minio /data)"
  printf 'central_telemetry_spool=%s\n' "$(central_volume telemetry-service /app/data/telemetry-ingestion)"
  printf 'edge_mqtt=%s\n' "$(edge_volume mqtt /mosquitto/data)"
  printf 'edge_sqlite=%s\n' "$(edge_volume device-agent /var/lib/nexolab)"
}

assert_snapshot() {
  local path="$1"
  [[ "$(wc -l < "$path" | tr -d ' ')" == "6" ]] || {
    echo "Expected six required persistent-data mounts:" >&2
    cat "$path" >&2
    return 1
  }
  [[ "$(cut -d= -f2- "$path" | sort -u | wc -l | tr -d ' ')" == "6" ]] || {
    echo "Required persistent-data mounts do not resolve to six distinct volumes:" >&2
    cat "$path" >&2
    return 1
  }
}

verify_markers() {
  local postgres_marker mqtt_marker minio_marker edge_marker
  postgres_marker="$("${CENTRAL[@]}" exec -T postgres sh -ec \
    'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT marker FROM offline_bundle_drill WHERE marker='"'"'offline-bundle-v1'"'"';"' \
    | tr -d '\r\n')"
  mqtt_marker="$("${CENTRAL[@]}" exec -T mqtt \
    mosquitto_sub -h 127.0.0.1 -t nexolab/offline-bundle/drill -C 1 -W 5 \
    | tr -d '\r\n')"
  minio_marker="$("${CENTRAL[@]}" run --rm -T --no-deps --entrypoint /bin/sh minio-init -ec '
    mc alias set central http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc cat "central/$OBJECT_STORAGE_BUCKET/offline-bundle/marker.txt"
  ' | tr -d '\r\n')"
  edge_marker="$("${EDGE[@]}" exec -T device-agent /usr/bin/python3 -c \
    'from pathlib import Path; print(Path("/var/lib/nexolab/offline-bundle.marker").read_text(encoding="utf-8"), end="")' \
    | tr -d '\r\n')"

  [[ "$postgres_marker" == "offline-bundle-v1" ]] || { echo "PostgreSQL marker mismatch: $postgres_marker" >&2; return 1; }
  [[ "$mqtt_marker" == "offline-bundle-v1" ]] || { echo "MQTT marker mismatch: $mqtt_marker" >&2; return 1; }
  [[ "$minio_marker" == "offline-bundle-v1" ]] || { echo "MinIO marker mismatch: $minio_marker" >&2; return 1; }
  [[ "$edge_marker" == "offline-bundle-v1" ]] || { echo "Edge marker mismatch: $edge_marker" >&2; return 1; }
}

BEFORE="$EVIDENCE_DIR/volumes-before.txt"
AFTER_UPDATE="$EVIDENCE_DIR/volumes-after-update.txt"
AFTER_ROLLBACK="$EVIDENCE_DIR/volumes-after-rollback.txt"

snapshot_required_volumes > "$BEFORE"
assert_snapshot "$BEFORE"
echo "Required persistent-data volumes before update:"
cat "$BEFORE"

"${CENTRAL[@]}" exec -T postgres sh -ec \
  'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
CREATE TABLE IF NOT EXISTS offline_bundle_drill (
  marker text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO offline_bundle_drill(marker) VALUES ('offline-bundle-v1')
  ON CONFLICT (marker) DO NOTHING;
SQL

"${CENTRAL[@]}" exec -T mqtt \
  mosquitto_pub -h 127.0.0.1 -t nexolab/offline-bundle/drill -m offline-bundle-v1 -r

printf 'offline-bundle-v1' | "${CENTRAL[@]}" run --rm -T --no-deps \
  --entrypoint /bin/sh minio-init -ec '
    cat > /tmp/offline-bundle-marker
    mc alias set central http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc cp /tmp/offline-bundle-marker "central/$OBJECT_STORAGE_BUCKET/offline-bundle/marker.txt" >/dev/null
  '

"${EDGE[@]}" exec -T device-agent /usr/bin/python3 -c \
  'from pathlib import Path; Path("/var/lib/nexolab/offline-bundle.marker").write_text("offline-bundle-v1", encoding="utf-8")'

verify_markers
echo "All service-level persistence markers were seeded and verified."

ORIGINAL_DASHBOARD="$OFFLINE_DASHBOARD_IMAGE"
ORIGINAL_TELEMETRY="$OFFLINE_TELEMETRY_IMAGE"
ORIGINAL_DEVICE_AGENT="$OFFLINE_DEVICE_AGENT_IMAGE"
UPDATE_DASHBOARD="${ORIGINAL_DASHBOARD}-update"
UPDATE_TELEMETRY="${ORIGINAL_TELEMETRY}-update"
UPDATE_DEVICE_AGENT="${ORIGINAL_DEVICE_AGENT}-update"

docker tag "$ORIGINAL_DASHBOARD" "$UPDATE_DASHBOARD"
docker tag "$ORIGINAL_TELEMETRY" "$UPDATE_TELEMETRY"
docker tag "$ORIGINAL_DEVICE_AGENT" "$UPDATE_DEVICE_AGENT"

export OFFLINE_DASHBOARD_IMAGE="$UPDATE_DASHBOARD"
export OFFLINE_TELEMETRY_IMAGE="$UPDATE_TELEMETRY"
export OFFLINE_DEVICE_AGENT_IMAGE="$UPDATE_DEVICE_AGENT"
"${CENTRAL[@]}" up -d --no-build --pull never --force-recreate --wait
"${EDGE[@]}" up -d --no-build --pull never --force-recreate --wait
snapshot_required_volumes > "$AFTER_UPDATE"
assert_snapshot "$AFTER_UPDATE"
cmp "$BEFORE" "$AFTER_UPDATE"
verify_markers
bash "$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" \
  --central-env "$CENTRAL_ENV" --edge-env "$EDGE_ENV"
echo "Update recreation preserved all required volumes and markers."

export OFFLINE_DASHBOARD_IMAGE="$ORIGINAL_DASHBOARD"
export OFFLINE_TELEMETRY_IMAGE="$ORIGINAL_TELEMETRY"
export OFFLINE_DEVICE_AGENT_IMAGE="$ORIGINAL_DEVICE_AGENT"
"${CENTRAL[@]}" up -d --no-build --pull never --force-recreate --wait
"${EDGE[@]}" up -d --no-build --pull never --force-recreate --wait
snapshot_required_volumes > "$AFTER_ROLLBACK"
assert_snapshot "$AFTER_ROLLBACK"
cmp "$BEFORE" "$AFTER_ROLLBACK"
verify_markers
bash "$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" \
  --central-env "$CENTRAL_ENV" --edge-env "$EDGE_ENV"
echo "Rollback recreation preserved all required volumes and markers."
