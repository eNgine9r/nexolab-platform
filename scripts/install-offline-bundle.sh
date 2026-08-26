#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: install-offline-bundle.sh --central-env PATH [--edge-env PATH] [--skip-edge] [--local-auth] [--runtime-mode lan|standalone] [--hardware] [--qemu-arm64-validation]

Loads the verified image archive and starts NEXOLAB with Docker Compose
`--pull never`. Existing named volumes are preserved. This script never adds
the volume-removal flag to Compose shutdown and never writes secrets into the bundle.
EOF
}

CENTRAL_ENV=""
EDGE_ENV=""
SKIP_EDGE=false
LOCAL_AUTH=false
RUNTIME_MODE=""
HARDWARE=false
QEMU_ARM64_VALIDATION=false
while (($#)); do
  case "$1" in
    --central-env) CENTRAL_ENV="${2:?}"; shift 2 ;;
    --edge-env) EDGE_ENV="${2:?}"; shift 2 ;;
    --skip-edge) SKIP_EDGE=true; shift ;;
    --local-auth) LOCAL_AUTH=true; shift ;;
    --runtime-mode) RUNTIME_MODE="${2:?}"; shift 2 ;;
    --hardware) HARDWARE=true; shift ;;
    --qemu-arm64-validation) QEMU_ARM64_VALIDATION=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "$CENTRAL_ENV" && -f "$CENTRAL_ENV" ]] || {
  echo "--central-env must reference an external environment file" >&2
  exit 2
}
if [[ -n "$RUNTIME_MODE" && "$RUNTIME_MODE" != "lan" && "$RUNTIME_MODE" != "standalone" ]]; then
  echo "--runtime-mode must be lan or standalone" >&2
  exit 2
fi
if [[ "$SKIP_EDGE" == false ]]; then
  [[ -n "$EDGE_ENV" && -f "$EDGE_ENV" ]] || {
    echo "--edge-env is required unless --skip-edge is used" >&2
    exit 2
  }
fi
if [[ "$HARDWARE" == true ]]; then
  [[ "$SKIP_EDGE" == false ]] || { echo "--hardware cannot be combined with --skip-edge" >&2; exit 2; }
  [[ -n "$RUNTIME_MODE" ]] || { echo "--hardware requires --runtime-mode" >&2; exit 2; }
fi
if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
  [[ "$SKIP_EDGE" == false ]] || { echo "--qemu-arm64-validation requires the edge stack" >&2; exit 2; }
  [[ "$HARDWARE" == false ]] || { echo "--qemu-arm64-validation cannot be combined with --hardware" >&2; exit 2; }
  [[ "$(uname -m)" == "x86_64" ]] || { echo "--qemu-arm64-validation is restricted to an x86_64 emulation host" >&2; exit 2; }
fi

for command in docker python3; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done
docker compose version >/dev/null

if [[ "$LOCAL_AUTH" == true ]]; then
  LOCAL_AUTH_EXPORTS="$(python3 - "$CENTRAL_ENV" <<'PYLOCALAUTH'
import os
import shlex
import sys
from pathlib import Path

env_path = Path(sys.argv[1]).resolve()
values = {}
for raw in env_path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip()
for key in ("AUTH_LOCAL_PRIVATE_KEY_HOST_FILE", "AUTH_LOCAL_PUBLIC_KEY_HOST_FILE"):
    raw = values.get(key, "").strip()
    if not raw:
        raise SystemExit(f"local-auth external host path is missing: {key}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = env_path.parent / candidate
    candidate = candidate.resolve()
    if not candidate.is_file() or not os.access(candidate, os.R_OK):
        raise SystemExit(f"local-auth external host file is not readable: {key}")
    print(f"export {key}={shlex.quote(str(candidate))}")
PYLOCALAUTH
  )" || exit $?
  eval "$LOCAL_AUTH_EXPORTS"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERIFY="$BUNDLE_ROOT/scripts/verify-offline-bundle.py"
MANIFEST="$BUNDLE_ROOT/manifest.json"
IMAGE_ARCHIVE="$BUNDLE_ROOT/images/nexolab-images.tar"
CENTRAL_BASE="$BUNDLE_ROOT/deploy/compose/compose.central.yaml"
CENTRAL_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.central.offline.yaml"
EDGE_BASE="$BUNDLE_ROOT/deploy/compose/compose.edge.yaml"
EDGE_OFFLINE="$BUNDLE_ROOT/deploy/offline/compose.edge.offline.yaml"
CENTRAL_STANDALONE="$BUNDLE_ROOT/deploy/compose/compose.central-standalone.yaml"
EDGE_HARDWARE="$BUNDLE_ROOT/deploy/compose/compose.hardware.yaml"
EDGE_BRIDGE="$BUNDLE_ROOT/deploy/compose/compose.edge-central-bridge.yaml"
EDGE_STANDALONE="$BUNDLE_ROOT/deploy/compose/compose.edge-standalone.yaml"

if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
  python3 - "$MANIFEST" <<'PYQEMU'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if manifest.get("platform") != "linux/arm64":
    raise SystemExit("--qemu-arm64-validation requires a linux/arm64 bundle")
PYQEMU
fi

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

DASHBOARD_BIND_ADDRESS="$(python3 - "$MANIFEST" "$CENTRAL_ENV" <<'PYBIND'
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
env = {}
for raw in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()

configured_bind = env.get("DASHBOARD_BIND_ADDRESS", "")
if configured_bind:
    print(configured_bind)
else:
    host = urlparse(manifest["dashboard"]["origin"]).hostname
    if not host:
        raise SystemExit("dashboard origin in manifest has no bindable host")
    print(host)
PYBIND
)"
export DASHBOARD_BIND_ADDRESS

CENTRAL=(docker compose --env-file "$CENTRAL_ENV" -f "$CENTRAL_BASE" -f "$CENTRAL_OFFLINE")
if [[ "$RUNTIME_MODE" == "standalone" ]]; then
  CENTRAL+=( -f "$CENTRAL_STANDALONE" )
fi
if [[ "$LOCAL_AUTH" == true ]]; then
  CENTRAL+=( -f "$BUNDLE_ROOT/deploy/compose/compose.local-auth.yaml" )
fi
"${CENTRAL[@]}" config --quiet
"${CENTRAL[@]}" up -d --no-build --pull never --wait

if [[ "$SKIP_EDGE" == false ]]; then
  EDGE=(docker compose --env-file "$EDGE_ENV" -f "$EDGE_BASE" -f "$EDGE_OFFLINE")
  if [[ "$HARDWARE" == true ]]; then
    python3 - "$EDGE_ENV" <<'PYHW'
import sys
from pathlib import Path

env = {}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    env[key.strip()] = value.strip()
serial = env.get("RS485_HOST_DEVICE", "")
mode = env.get("HARDWARE_DEVICE_MODE", "xjp60d").lower()
if not serial.startswith("/dev/serial/by-id/"):
    raise SystemExit("hardware package install requires stable RS485_HOST_DEVICE=/dev/serial/by-id/...")
if mode in {"simulator", "simulation", "demo", "mock", "disabled"}:
    raise SystemExit("hardware package install refuses simulator/demo/mock device mode")
PYHW
    EDGE+=( -f "$EDGE_HARDWARE" -f "$EDGE_BRIDGE" )
    if [[ "$RUNTIME_MODE" == "standalone" ]]; then
      EDGE+=( -f "$EDGE_STANDALONE" )
    fi
  fi
  "${EDGE[@]}" config --quiet
  if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
    "${EDGE[@]}" up -d --no-build --pull never
  else
    "${EDGE[@]}" up -d --no-build --pull never --wait
  fi
fi

SMOKE_ARGS=(--central-env "$CENTRAL_ENV")
if [[ "$LOCAL_AUTH" == true ]]; then
  SMOKE_ARGS+=(--local-auth)
fi
if [[ "$SKIP_EDGE" == true ]]; then
  SMOKE_ARGS+=(--skip-edge)
else
  SMOKE_ARGS+=(--edge-env "$EDGE_ENV")
  if [[ "$QEMU_ARM64_VALIDATION" == true ]]; then
    SMOKE_ARGS+=(--edge-health-timeout-seconds 120)
  fi
fi
"$BUNDLE_ROOT/scripts/offline-bundle-smoke.sh" "${SMOKE_ARGS[@]}"

echo "NEXOLAB offline bundle is installed and verified. Existing volumes were preserved."
