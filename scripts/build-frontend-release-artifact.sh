#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: build-frontend-release-artifact.sh --platform linux/arm64|linux/amd64 \
  --api-base-url URL --websocket-url URL --auth-provider PROVIDER \
  --organization-id UUID --output DIR

Builds a self-contained production Dashboard runtime artifact for a target Linux
architecture. The connected builder may use internet; the resulting artifact is
consumed offline by the Raspberry Pi deployment path.
EOF
}

PLATFORM=""
API_BASE_URL=""
WEBSOCKET_URL=""
AUTH_PROVIDER=""
ORGANIZATION_ID=""
OUTPUT=""

while (($#)); do
  case "$1" in
    --platform) PLATFORM="${2:?}"; shift 2 ;;
    --api-base-url) API_BASE_URL="${2:?}"; shift 2 ;;
    --websocket-url) WEBSOCKET_URL="${2:?}"; shift 2 ;;
    --auth-provider) AUTH_PROVIDER="${2:?}"; shift 2 ;;
    --organization-id) ORGANIZATION_ID="${2:?}"; shift 2 ;;
    --output) OUTPUT="${2:?}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 64 ;;
  esac
done

[[ "$PLATFORM" == "linux/arm64" || "$PLATFORM" == "linux/amd64" ]] || {
  echo "ERROR: --platform must be linux/arm64 or linux/amd64" >&2
  exit 64
}
[[ "$API_BASE_URL" =~ ^https?:// ]] || { echo "ERROR: invalid API URL" >&2; exit 64; }
[[ "$WEBSOCKET_URL" =~ ^wss?:// ]] || { echo "ERROR: invalid WebSocket URL" >&2; exit 64; }
[[ "$AUTH_PROVIDER" =~ ^(disabled|local|acceptance|supabase)$ ]] || {
  echo "ERROR: unsupported auth provider" >&2
  exit 64
}
[[ -n "$ORGANIZATION_ID" && -n "$OUTPUT" ]] || { usage >&2; exit 64; }

for command in docker git python3 sha256sum tar file; do
  command -v "$command" >/dev/null || { echo "ERROR: missing command: $command" >&2; exit 69; }
done

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "ERROR: refusing to build frontend artifact from a dirty working tree" >&2
  exit 70
fi
SOURCE_SHA="$(git rev-parse HEAD)"
NODE_VERSION="$(tr -d '[:space:]' < .nvmrc)"
ARCH="${PLATFORM#linux/}"
IMAGE="nexolab/frontend-release:${SOURCE_SHA:0:12}-${ARCH}"
OUTPUT="$(mkdir -p "$OUTPUT" && cd "$OUTPUT" && pwd)"
if find "$OUTPUT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "ERROR: output directory must be empty: $OUTPUT" >&2
  exit 73
fi
STAGING="$OUTPUT/.runtime-staging"
mkdir -p "$STAGING"

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "${CONTAINER_ID:-}" ]]; then docker rm -f "$CONTAINER_ID" >/dev/null 2>&1; fi
  docker image rm -f "$IMAGE" >/dev/null 2>&1 || true
  rm -rf "$STAGING"
  exit "$rc"
}
trap cleanup EXIT INT TERM

NODE_IMAGE="node:${NODE_VERSION}-bookworm-slim"
docker buildx build \
  --platform "$PLATFORM" \
  --load \
  --pull \
  --provenance=false \
  --label "org.opencontainers.image.source=https://github.com/eNgine9r/nexolab-platform" \
  --label "org.opencontainers.image.revision=$SOURCE_SHA" \
  --label "org.opencontainers.image.version=$SOURCE_SHA" \
  --tag "$IMAGE" \
  --file infrastructure/offline/Dockerfile.dashboard \
  --build-arg "NODE_IMAGE=$NODE_IMAGE" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_DATA_MODE=live" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_API_BASE_URL=$API_BASE_URL" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=$WEBSOCKET_URL" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=$AUTH_PROVIDER" \
  --build-arg "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=$ORGANIZATION_ID" \
  .

IMAGE_OS="$(docker image inspect "$IMAGE" --format '{{.Os}}')"
IMAGE_ARCH="$(docker image inspect "$IMAGE" --format '{{.Architecture}}')"
IMAGE_REVISION="$(docker image inspect "$IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')"
[[ "$IMAGE_OS/$IMAGE_ARCH" == "$PLATFORM" ]] || { echo "ERROR: built image platform mismatch" >&2; exit 70; }
[[ "$IMAGE_REVISION" == "$SOURCE_SHA" ]] || { echo "ERROR: built image source label mismatch" >&2; exit 70; }

CONTAINER_ID="$(docker create "$IMAGE")"
docker cp "$CONTAINER_ID:/app/.next" "$STAGING/.next"
docker cp "$CONTAINER_ID:/app/node_modules" "$STAGING/node_modules"
docker cp "$CONTAINER_ID:/app/package.json" "$STAGING/package.json"
docker cp "$CONTAINER_ID:/app/package-lock.json" "$STAGING/package-lock.json"
cmp -s package.json "$STAGING/package.json"
cmp -s package-lock.json "$STAGING/package-lock.json"

source scripts/lib/raspberry-pi-frontend-release.sh
nexolab_frontend_verify_public_contract \
  "$STAGING" live "$API_BASE_URL" "$WEBSOCKET_URL" "$AUTH_PROVIDER" "$ORGANIZATION_ID" \
  "$OUTPUT/frontend-public-contract.txt"
{
  find "$STAGING/.next" "$STAGING/node_modules" -type f -exec file {} + \
    | grep -E 'ELF|Mach-O|PE32' || true
} > "$OUTPUT/frontend-native-files.txt"
if [[ "$PLATFORM" == "linux/arm64" ]]; then
  if grep -E 'Mach-O|PE32' "$OUTPUT/frontend-native-files.txt" >/dev/null \
    || grep 'ELF' "$OUTPUT/frontend-native-files.txt" | grep -Ev 'ARM aarch64|ARM64|aarch64' >/dev/null; then
    echo "ERROR: non-ARM64 native binary found in ARM64 runtime" >&2
    exit 70
  fi
else
  if grep -E 'Mach-O|PE32' "$OUTPUT/frontend-native-files.txt" >/dev/null \
    || grep 'ELF' "$OUTPUT/frontend-native-files.txt" | grep -Ev 'x86-64|x86_64|AMD64' >/dev/null; then
    echo "ERROR: non-amd64 native binary found in amd64 runtime" >&2
    exit 70
  fi
fi

(
  cd "$STAGING"
  find .next node_modules -type f -print0 | sort -z | xargs -0 sha256sum
) > "$OUTPUT/frontend-runtime-files-sha256.txt"

tar --sort=name --mtime='UTC 1970-01-01' --owner=0 --group=0 --numeric-owner \
  -czf "$OUTPUT/frontend-runtime.tar.gz" -C "$STAGING" .next node_modules
cp package.json package-lock.json "$OUTPUT/"
printf '%s\n' "$SOURCE_SHA" > "$OUTPUT/frontend-source-sha.txt"
sha256sum "$OUTPUT/package.json" "$OUTPUT/package-lock.json" \
  | sed "s#${OUTPUT}/##" > "$OUTPUT/frontend-package-sha256.txt"
cat > "$OUTPUT/frontend-runtime-contract.txt" <<EOF
runtime_mode=live
api_base_url=$API_BASE_URL
websocket_url=$WEBSOCKET_URL
auth_provider=$AUTH_PROVIDER
organization_id=$ORGANIZATION_ID
EOF
printf '%s\n' "$PLATFORM" > "$OUTPUT/frontend-platform.txt"
printf '%s\n' "$NODE_VERSION" > "$OUTPUT/frontend-node-version.txt"
printf '%s\n' "$(cat "$STAGING/.next/BUILD_ID")" > "$OUTPUT/frontend-build-id.txt"

(
  cd "$OUTPUT"
  sha256sum \
    frontend-runtime.tar.gz \
    package.json \
    package-lock.json \
    frontend-source-sha.txt \
    frontend-package-sha256.txt \
    frontend-runtime-contract.txt \
    frontend-platform.txt \
    frontend-node-version.txt \
    frontend-build-id.txt \
    frontend-runtime-files-sha256.txt \
    frontend-public-contract.txt \
    frontend-native-files.txt > frontend-artifact-sha256.txt
)

echo "source_sha=$SOURCE_SHA"
echo "platform=$PLATFORM"
echo "node_version=$NODE_VERSION"
echo "build_id=$(cat "$OUTPUT/frontend-build-id.txt")"
echo "artifact=$OUTPUT/frontend-runtime.tar.gz"
