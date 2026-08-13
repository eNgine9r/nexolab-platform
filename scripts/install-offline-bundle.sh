#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: install-offline-bundle.sh --central-env PATH [--edge-env PATH] [--skip-edge] [--local-auth]

Loads the verified image archive and starts NEXOLAB with Docker Compose
`--pull never`. Existing named volumes are preserved. This script never adds
the volume-removal flag to Compose shutdown and never writes secrets into the bundle.
EOF
}

CENTRAL_ENV=""
EDGE_ENV=""
SKIP_EDGE=false
LOCAL_AUTH=false
while (($#)); do
  case "$1" in
    --central-env) CENTRAL_ENV="${2:?}"; shift 2 ;;
    --edge-env) EDGE_ENV="${2:?}"; shift 2 ;;
    --skip-edge) SKIP_EDGE=true; shift ;;
    --local-auth) LOCAL_AUTH=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$CENTRAL_ENV" && -f "$CENTRAL_ENV" ]] || {
  echo "--central-env must reference an external environment file" >&2
  exit 2
}
if [[ "$SKIP_EDGE" == false ]]; then
  [[ -n "$EDGE_ENV" && -f "$EDGE_ENV" ]] || {
    echo "--edge-env is required unless --skip-edge is used" >&2
    exit 2
  }
fi

for command in docker python3; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFY="$BUNDLE_ROOT/scripts/verify-offline-bundle.py"
MANIFEST="$BUNDLE_ROOT/manifest.json"
IMAGE_ARCHIVE="$BUNDLE_ROOT/images/nexolab-images.tar"
CENTRAL_BASE="$BUNDLE_ROOT/deploy/compose/compose.central.yaml"
CENTRAL_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.central.offline.yaml"
EDGE_BASE="$BUNDLE_ROOT/deploy/compose/compose.edge.yaml"
EDGE_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.edge.offline.yaml"

python3 "$VERIFY" "$BUNDLE_ROOT"
docker load --input "$IMAGE_ARCHIVE"
eval "$(python3 "$VERIFY" "$BUNDLE_ROOT" --check-loaded-images --emit-shell-env)"
export OFFLINE_DASHBOARD_IMAGE OFFLINE_TELEMETRY_IMAGE OFFLINE_DEVICE_AGENT_IMAGE
export OFFLINE_MQTT_IMAGE OFFLINE_POSTGRES_IMAGE OFFLINE_MINIO_IMAGE OFFLINE_MINIO_CLIENT_IMAGE

python3 - "$MANIFEST" "$CENTRAL_ENV" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
env = {}
for raw in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()
origin = manifest["dashboard"]["origin"]
allowed = {value.strip() for value in env.get("CORS_ALLOWED_ORIGINS", "").split(",") if value.strip()}
if origin not in allowed:
    raise SystemExit(
        f"CORS_ALLOWED_ORIGINS must include the dashboard origin recorded in the bundle: {origin}"
    )
if env.get("AUTH_MODE", "disabled") != "disabled" and env.get("AUTH_JWT_JWKS_URL"):
    raise SystemExit(
        "Offline install cannot depend on AUTH_JWT_JWKS_URL. Use a local/static-key identity design from Issue #188."
    )
PY

CENTRAL=(docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_BASE" -f "$CENTRAL_OFFLINE")
if [[ "$LOCAL_AUTH" == true ]]; then
  CENTRAL+=( -f "$BUNDLE_ROOT/deploy/compose/compose.local-auth.yaml" )
fi
"${CENTRAL[@]}" config --quiet
"${CENTRAL[@]}" up -d --no-build --pull never --wait

if [[ "$SKIP_EDGE" == false ]]; then
  EDGE=(docker compose --env-file "$EDGE_ENV" -f "$EDGE_BASE" -f "$EDGE_OFFLINE")
  "${EDGE[@]}" config --quiet
  "${EDGE[@]}" up -d --no-build --pull never --wait
fi

SMOKE_ARGS=(--central-env "$CENTRAL_ENV")
if [[ "$LOCAL_AUTH" == true ]]; then
  SMOKE_ARGS+=(--local-auth)
fi
if [[ "$SKIP_EDGE" == true ]]; then
  SMOKE_ARGS+=(--skip-edge)
else
  SMOKE_ARGS+=(--edge-env "$EDGE_ENV")
fi
"$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" "${SMOKE_ARGS[@]}"

echo "NEXOLAB offline bundle is installed and verified. Existing volumes were preserved."
