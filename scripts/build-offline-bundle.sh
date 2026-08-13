#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: build-offline-bundle.sh --version VERSION --platform linux/amd64|linux/arm64 \
  --dashboard-origin URL --api-base-url URL --websocket-url URL \
  [--schema-head REVISION] [--upgrade-from-schema-head REVISION] \
  [--runtime-compatible-schema-head REVISION] \
  [--auth-provider disabled|local|acceptance|supabase] [--output DIR]

Builds a versioned NEXOLAB offline bundle. This command is intentionally run on a
connected build host; the resulting archive is self-contained for disconnected
installation. Secrets and site .env files are never included.
EOF
}

VERSION=""
PLATFORM=""
DASHBOARD_ORIGIN=""
API_BASE_URL=""
WEBSOCKET_URL=""
AUTH_PROVIDER="disabled"
SCHEMA_HEAD=""
UPGRADE_FROM_SCHEMA_HEADS=()
RUNTIME_COMPATIBLE_SCHEMA_HEADS=()
OUTPUT_DIR="${PWD}/dist/offline"
TRIVY_IMAGE="${TRIVY_IMAGE:-aquasec/trivy:0.69.3}"

while (($#)); do
  case "$1" in
    --version) VERSION="${2:?}"; shift 2 ;;
    --platform) PLATFORM="${2:?}"; shift 2 ;;
    --dashboard-origin) DASHBOARD_ORIGIN="${2:?}"; shift 2 ;;
    --api-base-url) API_BASE_URL="${2:?}"; shift 2 ;;
    --websocket-url) WEBSOCKET_URL="${2:?}"; shift 2 ;;
    --auth-provider) AUTH_PROVIDER="${2:?}"; shift 2 ;;
    --schema-head) SCHEMA_HEAD="${2:?}"; shift 2 ;;
    --upgrade-from-schema-head) UPGRADE_FROM_SCHEMA_HEADS+=("${2:?}"); shift 2 ;;
    --runtime-compatible-schema-head) RUNTIME_COMPATIBLE_SCHEMA_HEADS+=("${2:?}"); shift 2 ;;
    --output) OUTPUT_DIR="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

for command in docker git python3 sha256sum tar; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 1; }
done

[[ -n "$VERSION" ]] || { echo "--version is required" >&2; exit 2; }
[[ "$PLATFORM" == "linux/amd64" || "$PLATFORM" == "linux/arm64" ]] || {
  echo "--platform must be linux/amd64 or linux/arm64" >&2
  exit 2
}
[[ "$DASHBOARD_ORIGIN" =~ ^https?:// ]] || { echo "Invalid --dashboard-origin" >&2; exit 2; }
[[ "$API_BASE_URL" =~ ^https?:// ]] || { echo "Invalid --api-base-url" >&2; exit 2; }
[[ "$WEBSOCKET_URL" =~ ^wss?:// ]] || { echo "Invalid --websocket-url" >&2; exit 2; }
[[ "$AUTH_PROVIDER" =~ ^(disabled|local|acceptance|supabase)$ ]] || {
  echo "--auth-provider must be disabled, local, acceptance or supabase" >&2
  exit 2
}
[[ "$VERSION" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "Invalid bundle version" >&2; exit 2; }

git diff --quiet -- . ':!dist' || {
  echo "Refusing to build from a dirty working tree" >&2
  exit 1
}

SOURCE_COMMIT="$(git rev-parse HEAD)"
if [[ -z "$SCHEMA_HEAD" ]]; then
  SCHEMA_HEAD="$(python3 - <<'PY'
import ast
from pathlib import Path

revisions = set()
parents = set()
for path in Path("services/telemetry-service/migrations/versions").glob("*.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name in {"revision", "down_revision"} and value is not None:
            values[name] = ast.literal_eval(value)
    revision = values.get("revision")
    parent = values.get("down_revision")
    if revision:
        revisions.add(revision)
    if isinstance(parent, str):
        parents.add(parent)
    elif isinstance(parent, (tuple, list)):
        parents.update(parent)
heads = sorted(revisions - parents)
if len(heads) != 1:
    raise SystemExit(f"Expected one Alembic head, found {heads}")
print(heads[0])
PY
)"
fi
ARCH="${PLATFORM#linux/}"
BUNDLE_NAME="nexolab-offline-${VERSION}-${ARCH}"
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
STAGING="${OUTPUT_DIR}/${BUNDLE_NAME}"
ARCHIVE="${OUTPUT_DIR}/${BUNDLE_NAME}.tar.gz"
rm -rf "$STAGING" "$ARCHIVE" "${ARCHIVE}.sha256"
mkdir -p "$STAGING"/{deploy/compose,deploy/offline,images,evidence,scripts,docs}

DASHBOARD_IMAGE="nexolab/dashboard:${VERSION}-${ARCH}"
TELEMETRY_IMAGE="nexolab/telemetry-service:${VERSION}-${ARCH}"
DEVICE_AGENT_IMAGE="nexolab/device-agent:${VERSION}-${ARCH}"
MQTT_IMAGE="eclipse-mosquitto:2.0.22"
POSTGRES_IMAGE="postgres:16-alpine"
MINIO_IMAGE="minio/minio:RELEASE.2025-09-07T16-13-09Z"
MINIO_CLIENT_IMAGE="minio/mc:RELEASE.2025-08-13T08-35-41Z"

build_image() {
  local reference="$1" dockerfile="$2" context="$3"
  shift 3
  docker buildx build \
    --platform "$PLATFORM" \
    --load \
    --pull \
    --provenance=false \
    --label "org.opencontainers.image.source=https://github.com/eNgine9r/nexolab-platform" \
    --label "org.opencontainers.image.revision=${SOURCE_COMMIT}" \
    --label "org.opencontainers.image.version=${VERSION}" \
    --tag "$reference" \
    --file "$dockerfile" \
    "$@" \
    "$context"
}

build_image "$DASHBOARD_IMAGE" infrastructure/offline/Dockerfile.dashboard . \
  --build-arg "NEXT_PUBLIC_NEXOLAB_DATA_MODE=live" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_API_BASE_URL=${API_BASE_URL}" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=${WEBSOCKET_URL}" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=${AUTH_PROVIDER}" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001"
build_image "$TELEMETRY_IMAGE" services/telemetry-service/Dockerfile services/telemetry-service
build_image "$DEVICE_AGENT_IMAGE" services/device-agent/Dockerfile services/device-agent

for image in "$MQTT_IMAGE" "$POSTGRES_IMAGE" "$MINIO_IMAGE" "$MINIO_CLIENT_IMAGE"; do
  docker pull --platform "$PLATFORM" "$image"
done

docker pull "$TRIVY_IMAGE" >/dev/null

IMAGE_RECORDS=(
  "dashboard=${DASHBOARD_IMAGE}"
  "telemetry-service=${TELEMETRY_IMAGE}"
  "device-agent=${DEVICE_AGENT_IMAGE}"
  "mqtt=${MQTT_IMAGE}"
  "postgres=${POSTGRES_IMAGE}"
  "minio=${MINIO_IMAGE}"
  "minio-client=${MINIO_CLIENT_IMAGE}"
)
IMAGE_REFS=(
  "$DASHBOARD_IMAGE"
  "$TELEMETRY_IMAGE"
  "$DEVICE_AGENT_IMAGE"
  "$MQTT_IMAGE"
  "$POSTGRES_IMAGE"
  "$MINIO_IMAGE"
  "$MINIO_CLIENT_IMAGE"
)

docker save --output "$STAGING/images/nexolab-images.tar" "${IMAGE_REFS[@]}"

for record in "${IMAGE_RECORDS[@]}"; do
  logical_id="${record%%=*}"
  image="${record#*=}"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$STAGING/evidence:/evidence" \
    "$TRIVY_IMAGE" image --quiet --format cyclonedx \
    --output "/evidence/${logical_id}.cdx.json" "$image"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$STAGING/evidence:/evidence" \
    "$TRIVY_IMAGE" image --quiet --format spdx-json \
    --output "/evidence/${logical_id}.spdx.json" "$image"
done

cp infrastructure/compose/compose.central.yaml "$STAGING/deploy/compose/"
cp infrastructure/compose/compose.edge.yaml "$STAGING/deploy/compose/"
cp infrastructure/compose/compose.local-auth.yaml "$STAGING/deploy/compose/"
cp infrastructure/compose/mosquitto.central.conf "$STAGING/deploy/compose/"
cp infrastructure/compose/mosquitto.conf "$STAGING/deploy/compose/"
cp infrastructure/compose/.env.central.example "$STAGING/deploy/compose/env.central.example"
cp infrastructure/compose/.env.edge.example "$STAGING/deploy/compose/env.edge.example"
cp infrastructure/offline/compose.central.offline.yaml "$STAGING/deploy/offline/"
cp infrastructure/offline/compose.edge.offline.yaml "$STAGING/deploy/offline/"
cp infrastructure/offline/nexolab-version-manager.service "$STAGING/deploy/offline/"
cp infrastructure/offline/nexolab-version-manager.path "$STAGING/deploy/offline/"
cp scripts/verify-offline-bundle.py "$STAGING/scripts/"
cp scripts/install-offline-bundle.sh "$STAGING/scripts/"
cp scripts/offline-bundle-smoke.sh "$STAGING/scripts/"
cp scripts/nexolab-version-manager.py "$STAGING/scripts/"
cp scripts/deploy-version-manager-service.sh "$STAGING/scripts/"
cp docs/operations/offline-installation.md "$STAGING/docs/"
cp docs/operations/local-version-management.md "$STAGING/docs/"
cp docs/security/local-operator-authentication.md "$STAGING/docs/"
chmod 0755 "$STAGING/scripts/"*.sh "$STAGING/scripts/"*.py

python3 - "$STAGING/evidence/provenance.json" "$SOURCE_COMMIT" "$VERSION" "$PLATFORM" "$TRIVY_IMAGE" "$AUTH_PROVIDER" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

output, commit, version, platform, trivy_image, auth_provider = sys.argv[1:]
payload = {
    "schema_version": 1,
    "source_repository": "eNgine9r/nexolab-platform",
    "source_commit": commit,
    "bundle_version": version,
    "platform": platform,
    "builder": "scripts/build-offline-bundle.sh",
    "sbom_generator": trivy_image,
    "dashboard_auth_provider": auth_provider,
    "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    "network_policy": "connected build; disconnected runtime",
    "secrets_included": False,
}
Path(output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

MANIFEST_ARGS=()
for record in "${IMAGE_RECORDS[@]}"; do
  MANIFEST_ARGS+=(--image "$record")
done
if ((${#UPGRADE_FROM_SCHEMA_HEADS[@]} == 0)); then
  UPGRADE_FROM_SCHEMA_HEADS+=("$SCHEMA_HEAD")
fi
if ((${#RUNTIME_COMPATIBLE_SCHEMA_HEADS[@]} == 0)); then
  RUNTIME_COMPATIBLE_SCHEMA_HEADS+=("$SCHEMA_HEAD")
fi
for revision in "${UPGRADE_FROM_SCHEMA_HEADS[@]}"; do
  MANIFEST_ARGS+=(--upgrade-from-schema-head "$revision")
done
for revision in "${RUNTIME_COMPATIBLE_SCHEMA_HEADS[@]}"; do
  MANIFEST_ARGS+=(--runtime-compatible-schema-head "$revision")
done
python3 scripts/generate-offline-bundle-manifest.py \
  --bundle-root "$STAGING" \
  --bundle-version "$VERSION" \
  --source-commit "$SOURCE_COMMIT" \
  --platform "$PLATFORM" \
  --schema-head "$SCHEMA_HEAD" \
  --dashboard-origin "$DASHBOARD_ORIGIN" \
  --dashboard-api-base-url "$API_BASE_URL" \
  --dashboard-websocket-url "$WEBSOCKET_URL" \
  --dashboard-auth-provider "$AUTH_PROVIDER" \
  "${MANIFEST_ARGS[@]}"

(
  cd "$STAGING"
  find . -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum \
    | sed 's#  \./#  #' > SHA256SUMS
)
python3 scripts/verify-offline-bundle.py "$STAGING" --check-loaded-images

tar --create --gzip --file "$ARCHIVE" --directory "$OUTPUT_DIR" "$BUNDLE_NAME"
printf '%s  %s\n' "$(sha256sum "$ARCHIVE" | awk '{print $1}')" "$(basename "$ARCHIVE")" \
  > "${ARCHIVE}.sha256"

printf 'Offline bundle created:\n  %s\n  %s\n' "$ARCHIVE" "${ARCHIVE}.sha256"
