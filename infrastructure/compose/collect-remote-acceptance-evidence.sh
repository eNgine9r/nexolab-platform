#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$COMPOSE_DIR/../.." && pwd)"
ENV_FILE="${1:-$COMPOSE_DIR/.env.central}"
EQUIPMENT_ID="${2:-}"
EVIDENCE_DIR="${3:-$ROOT_DIR/runtime/evidence/central-host-remote-acceptance-$(date -u +%Y%m%dT%H%M%SZ)}"

if [[ -z "$EQUIPMENT_ID" ]]; then
  printf 'Usage: %s [env-file] <equipment-id> [evidence-directory]\n' "$0" >&2
  exit 2
fi
if [[ "$EQUIPMENT_ID" != acceptance-* ]]; then
  printf 'Evidence collection is restricted to acceptance-* equipment ids.\n' >&2
  exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Central environment file not found: %s\n' "$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${OBJECT_STORAGE_BUCKET:?OBJECT_STORAGE_BUCKET is required}"

mkdir -p "$EVIDENCE_DIR"

compose() {
  docker compose \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_DIR/compose.central.yaml" \
    --file "$COMPOSE_DIR/compose.central-dashboard.yaml" \
    "$@"
}

compose config >"$EVIDENCE_DIR/compose-resolved.yaml"
compose ps --all >"$EVIDENCE_DIR/compose-ps.txt"
compose logs --since=30m --no-color dashboard telemetry-service telemetry-migrate minio minio-init postgres \
  >"$EVIDENCE_DIR/central-services.log" 2>&1

docker ps --format '{{.Names}}\t{{.Ports}}' | grep '^nexolab-central-' \
  >"$EVIDENCE_DIR/docker-published-ports.txt" || true

compose exec -T postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v equipment_id="$EQUIPMENT_ID" >"$EVIDENCE_DIR/postgresql-acceptance-state.txt" <<'SQL'
\pset pager off
SELECT equipment_id, version, image_id, json_array_length(placements) AS placement_count,
       created_at, updated_at
FROM refrigeration_layout_drafts
WHERE equipment_id = :'equipment_id';

SELECT equipment_id, revision, source_draft_version, image_id,
       json_array_length(placements) AS placement_count, published_by, published_at
FROM refrigeration_layout_revisions
WHERE equipment_id = :'equipment_id'
ORDER BY revision;

SELECT equipment_id, original_filename, media_type, size_bytes, width_px, height_px,
       storage_key, created_by, created_at
FROM equipment_images
WHERE equipment_id = :'equipment_id'
ORDER BY created_at;
SQL

compose run --rm --no-deps --entrypoint /bin/sh minio-init -ec '
  mc alias set central http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
  printf "anonymous_access:\n"
  mc anonymous get "central/$OBJECT_STORAGE_BUCKET"
  printf "objects:\n"
  mc ls --recursive "central/$OBJECT_STORAGE_BUCKET"
' >"$EVIDENCE_DIR/minio-acceptance-state.txt" 2>&1

if command -v tailscale >/dev/null 2>&1; then
  tailscale serve status >"$EVIDENCE_DIR/tailscale-serve-status.txt" 2>&1
  tailscale serve status --json >"$EVIDENCE_DIR/tailscale-serve-status.json" 2>&1 || true
fi

printf 'Central-host acceptance evidence: %s\n' "$EVIDENCE_DIR"
