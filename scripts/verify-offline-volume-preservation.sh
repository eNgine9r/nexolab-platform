#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: verify-offline-volume-preservation.sh \
  --bundle-root PATH \
  --central-env PATH \
  --edge-env PATH \
  --evidence-dir PATH \
  [--local-auth] \
  [--local-auth-refresh-token-file PATH] \
  [--qemu-arm64-validation]

Seeds service-level persistence markers, recreates the disconnected NEXOLAB
stack with update image tags, rolls back to the original tags, and proves that
all six required persistent-data volumes and markers survive both operations.
EOF
}

BUNDLE_ROOT=""
CENTRAL_ENV=""
EDGE_ENV=""
EVIDENCE_DIR=""
LOCAL_AUTH=false
LOCAL_AUTH_REFRESH_TOKEN_FILE=""
QEMU_ARM64_VALIDATION=false
while (($#)); do
  case "$1" in
    --bundle-root) BUNDLE_ROOT="${2:?}"; shift 2 ;;
    --central-env) CENTRAL_ENV="${2:?}"; shift 2 ;;
    --edge-env) EDGE_ENV="${2:?}"; shift 2 ;;
    --evidence-dir) EVIDENCE_DIR="${2:?}"; shift 2 ;;
    --local-auth) LOCAL_AUTH=true; shift ;;
    --local-auth-refresh-token-file) LOCAL_AUTH_REFRESH_TOKEN_FILE="${2:?}"; shift 2 ;;
    --qemu-arm64-validation) QEMU_ARM64_VALIDATION=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -d "$BUNDLE_ROOT" ]] || { echo "Bundle root not found: $BUNDLE_ROOT" >&2; exit 2; }
[[ -f "$CENTRAL_ENV" ]] || { echo "Central environment file not found: $CENTRAL_ENV" >&2; exit 2; }
[[ -f "$EDGE_ENV" ]] || { echo "Edge environment file not found: $EDGE_ENV" >&2; exit 2; }
[[ -n "$EVIDENCE_DIR" ]] || { echo "--evidence-dir is required" >&2; exit 2; }
mkdir -p "$EVIDENCE_DIR"
if [[ "$LOCAL_AUTH" == true ]]; then
  [[ -f "$LOCAL_AUTH_REFRESH_TOKEN_FILE" ]] || {
    echo "--local-auth-refresh-token-file is required with --local-auth" >&2
    exit 2
  }
fi
if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
  [[ "$(uname -m)" == "x86_64" ]] || { echo "--qemu-arm64-validation is restricted to an x86_64 emulation host" >&2; exit 2; }
  python3 - "$BUNDLE_ROOT/manifest.json" <<'PYQEMU'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("platform") != "linux/arm64":
    raise SystemExit("--qemu-arm64-validation requires a linux/arm64 bundle")
PYQEMU
fi

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
if [[ "$LOCAL_AUTH" == true ]]; then
  CENTRAL+=( -f "$BUNDLE_ROOT/deploy/compose/compose.local-auth.yaml" )
fi
EDGE=(docker compose --env-file "$EDGE_ENV" \
  -f "$BUNDLE_ROOT/deploy/compose/compose.edge.yaml" \
  -f "$BUNDLE_ROOT/deploy/offline/compose.edge.offline.yaml")
SMOKE_ARGS=(--central-env "$CENTRAL_ENV" --edge-env "$EDGE_ENV")
if [[ "$LOCAL_AUTH" == true ]]; then
  SMOKE_ARGS+=(--local-auth)
fi
if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
  SMOKE_ARGS+=(--edge-health-timeout-seconds 120)
fi

recreate_edge() {
  if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
    "${EDGE[@]}" up -d --no-build --pull never --force-recreate
  else
    "${EDGE[@]}" up -d --no-build --pull never --force-recreate --wait
  fi
}

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

central_env_value() {
  python3 - "$CENTRAL_ENV" "$1" <<'PYENV'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key = sys.argv[2]
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    name, value = line.split("=", 1)
    if name.strip() == key:
        print(value.strip().strip('"').strip("'"))
        raise SystemExit(0)
raise SystemExit(f"Missing {key} in {path}")
PYENV
}

CENTRAL_API_PORT=""
AUTH_ORGANIZATION_ID=""
if [[ "$LOCAL_AUTH" == true ]]; then
  CENTRAL_API_PORT="$(central_env_value CENTRAL_API_PORT)"
  AUTH_ORGANIZATION_ID="$(central_env_value AUTH_DEFAULT_ORGANIZATION_ID)"
  [[ "$CENTRAL_API_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || { echo "Invalid CENTRAL_API_PORT" >&2; exit 2; }
  (( CENTRAL_API_PORT <= 65535 )) || { echo "Invalid CENTRAL_API_PORT" >&2; exit 2; }
fi

refresh_local_auth_session() {
  local phase="$1"
  local finalize="${2:-false}"
  python3 - \
    "$LOCAL_AUTH_REFRESH_TOKEN_FILE" \
    "http://127.0.0.1:$CENTRAL_API_PORT" \
    "$AUTH_ORGANIZATION_ID" \
    "$phase" \
    "$finalize" \
    "$EVIDENCE_DIR/local-auth-continuity.txt" <<'PYAUTH'
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

refresh_path = Path(sys.argv[1])
base = sys.argv[2]
organization_id = sys.argv[3]
phase = sys.argv[4]
finalize = sys.argv[5] == "true"
evidence = Path(sys.argv[6])
old_refresh = refresh_path.read_text(encoding="utf-8").strip()
if not old_refresh:
    raise SystemExit("Local auth refresh token continuity file is empty")

def request(method, path, payload=None, token=None, expected=(200,)):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Organization-ID"] = organization_id
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    if status not in expected:
        raise SystemExit(f"{method} {path} returned unexpected HTTP {status}")
    parsed = json.loads(body) if body else None
    return status, parsed

_, refreshed = request(
    "POST", "/api/v1/auth/local/refresh", {"refresh_token": old_refresh}
)
new_refresh = refreshed["refresh_token"]
if new_refresh == old_refresh:
    raise SystemExit("Local auth refresh token did not rotate")
_, session = request(
    "GET", "/api/v1/auth/session", token=refreshed["access_token"]
)
if session["identity"]["provider"] != "nexolab-local":
    raise SystemExit(f"Local auth provider mismatch after {phase}")
memberships = session.get("memberships", [])
matching = [item for item in memberships if item.get("organization_id") == organization_id]
if len(matching) != 1 or "administrator" not in matching[0].get("roles", []):
    raise SystemExit(f"Local auth membership/RBAC continuity failed after {phase}")

if finalize:
    request(
        "POST", "/api/v1/auth/local/logout",
        {"refresh_token": new_refresh}, expected=(204,)
    )
    status, revoked = request(
        "GET", "/api/v1/auth/session",
        token=refreshed["access_token"], expected=(401,)
    )
    code = (revoked or {}).get("detail", {}).get("code")
    if status != 401 or code != "local_session_invalid":
        raise SystemExit("Local auth logout did not revoke persisted session")
    refresh_path.unlink(missing_ok=True)
else:
    refresh_path.write_text(new_refresh, encoding="utf-8")
    refresh_path.chmod(0o600)

with evidence.open("a", encoding="utf-8") as handle:
    handle.write(f"{phase}=refresh-session-ok")
    if finalize:
        handle.write(";logout-revocation-ok")
    handle.write("\n")
PYAUTH
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
recreate_edge
bash "$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" "${SMOKE_ARGS[@]}"
snapshot_required_volumes > "$AFTER_UPDATE"
assert_snapshot "$AFTER_UPDATE"
cmp "$BEFORE" "$AFTER_UPDATE"
verify_markers
if [[ "$LOCAL_AUTH" == true ]]; then
  refresh_local_auth_session update false
fi
echo "Update recreation preserved all required volumes, markers and auth continuity."

export OFFLINE_DASHBOARD_IMAGE="$ORIGINAL_DASHBOARD"
export OFFLINE_TELEMETRY_IMAGE="$ORIGINAL_TELEMETRY"
export OFFLINE_DEVICE_AGENT_IMAGE="$ORIGINAL_DEVICE_AGENT"
"${CENTRAL[@]}" up -d --no-build --pull never --force-recreate --wait
recreate_edge
bash "$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" "${SMOKE_ARGS[@]}"
snapshot_required_volumes > "$AFTER_ROLLBACK"
assert_snapshot "$AFTER_ROLLBACK"
cmp "$BEFORE" "$AFTER_ROLLBACK"
verify_markers
if [[ "$LOCAL_AUTH" == true ]]; then
  refresh_local_auth_session rollback true
fi
echo "Rollback recreation preserved all required volumes, markers and auth continuity."
