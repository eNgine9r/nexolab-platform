#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
BASE_COMPOSE="$COMPOSE_DIR/compose.central.yaml"
ACCEPTANCE_COMPOSE="$COMPOSE_DIR/compose.browser-acceptance.yaml"
RUN_SUFFIX="$(date -u +%Y%m%dt%H%M%Sz)-$$"

random_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    printf '%s' "${RUN_SUFFIX//[^a-zA-Z0-9]/}$(date +%s%N)"
  fi
}

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-nexolab-browser-acceptance-$RUN_SUFFIX}"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="${ACCEPTANCE_API_PORT:-18082}"
export CENTRAL_MQTT_PORT="${ACCEPTANCE_MQTT_PORT:-11884}"
export CENTRAL_OBJECT_STORAGE_PORT="${ACCEPTANCE_OBJECT_STORAGE_PORT:-19000}"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="${ACCEPTANCE_OBJECT_STORAGE_CONSOLE_PORT:-19001}"
export ACCEPTANCE_WEB_PORT="${ACCEPTANCE_WEB_PORT:-13000}"
export ACCEPTANCE_NETWORK_NAME="${ACCEPTANCE_NETWORK_NAME:-$COMPOSE_PROJECT_NAME-network}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${ACCEPTANCE_MQTT_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-mqtt}"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${ACCEPTANCE_POSTGRES_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-postgres}"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME:-$COMPOSE_PROJECT_NAME-object-storage}"
export POSTGRES_DB="${POSTGRES_DB:-nexolab}"
export POSTGRES_USER="${POSTGRES_USER:-nexolab}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(random_secret)}"
export MINIO_ROOT_USER="${MINIO_ROOT_USER:-nexolab-acceptance}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-$(random_secret)}"
export OBJECT_STORAGE_BUCKET="${OBJECT_STORAGE_BUCKET:-nexolab-equipment-images-acceptance}"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:$ACCEPTANCE_WEB_PORT"
export CORS_ALLOW_CREDENTIALS="false"
export RETENTION_ENABLED="false"
export TELEMETRY_SERVICE_IMAGE="${TELEMETRY_SERVICE_IMAGE:-nexolab-telemetry-service:browser-acceptance}"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="http://127.0.0.1:$CENTRAL_API_PORT"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:$CENTRAL_API_PORT/ws/telemetry"
export NEXT_PUBLIC_NEXOLAB_OPERATOR_ID="${NEXT_PUBLIC_NEXOLAB_OPERATOR_ID:-browser-acceptance-operator}"
export NEXOLAB_ACCEPTANCE_WEB_URL="http://127.0.0.1:$ACCEPTANCE_WEB_PORT"
export NEXT_TELEMETRY_DISABLED="1"

EVIDENCE_DIR="${NEXOLAB_ACCEPTANCE_EVIDENCE_DIR:-runtime/evidence/refrigeration-browser-acceptance-$RUN_SUFFIX}"
if [[ "$EVIDENCE_DIR" != /* ]]; then
  EVIDENCE_DIR="$ROOT_DIR/$EVIDENCE_DIR"
fi
export NEXOLAB_ACCEPTANCE_EVIDENCE_DIR="$EVIDENCE_DIR"
mkdir -p "$EVIDENCE_DIR"

STACK_STARTED=0

compose() {
  docker compose \
    --project-name "$COMPOSE_PROJECT_NAME" \
    --file "$BASE_COMPOSE" \
    --file "$ACCEPTANCE_COMPOSE" \
    "$@"
}

seed_camera_scoped_fixtures() {
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
INSERT INTO central_nodes (
    id,
    organization_id,
    node_id,
    display_name,
    state,
    state_reason,
    clock_warning_ms,
    clock_critical_ms,
    last_seen_at,
    last_clock_offset_ms,
    clock_status,
    clock_observed_at,
    created_by,
    created_at,
    updated_at
) VALUES (
    '00000000-0000-4000-8000-000000000202',
    '00000000-0000-0000-0000-000000000001',
    'kk2-acceptance',
    'Кліматична камера КК2',
    'active',
    'refrigeration browser acceptance fixture',
    30000,
    120000,
    CURRENT_TIMESTAMP,
    0,
    'ok',
    CURRENT_TIMESTAMP,
    'browser-acceptance',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
)
ON CONFLICT (organization_id, node_id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    state = EXCLUDED.state,
    state_reason = EXCLUDED.state_reason,
    last_seen_at = EXCLUDED.last_seen_at,
    updated_at = EXCLUDED.updated_at;

INSERT INTO telemetry_samples (
    event_id,
    node_id,
    captured_at,
    metric,
    value,
    unit,
    quality,
    source,
    equipment_id,
    channel_id,
    alarm,
    raw_value,
    raw_status,
    raw_payload,
    raw_payload_retained,
    received_at
) VALUES
    (
        '00000000-0000-4000-8000-000000002201',
        'kk2-acceptance',
        CURRENT_TIMESTAMP,
        'temperature',
        2.1,
        'degC',
        'good',
        'acceptance-fixture',
        'unassigned',
        'kk2-temp-01',
        NULL,
        21,
        0,
        '{"fixture":"refrigeration-browser-acceptance"}'::jsonb,
        TRUE,
        CURRENT_TIMESTAMP
    ),
    (
        '00000000-0000-4000-8000-000000002202',
        'kk2-acceptance',
        CURRENT_TIMESTAMP,
        'temperature',
        3.4,
        'degC',
        'good',
        'acceptance-fixture',
        'unassigned',
        'kk2-temp-02',
        NULL,
        34,
        0,
        '{"fixture":"refrigeration-browser-acceptance"}'::jsonb,
        TRUE,
        CURRENT_TIMESTAMP
    ),
    (
        '00000000-0000-4000-8000-000000002203',
        'kk2-acceptance',
        CURRENT_TIMESTAMP,
        'active_power',
        742.0,
        'W',
        'good',
        'acceptance-fixture',
        'unassigned',
        'kk2-power-01',
        NULL,
        742,
        0,
        '{"fixture":"refrigeration-browser-acceptance"}'::jsonb,
        TRUE,
        CURRENT_TIMESTAMP
    )
ON CONFLICT (event_id) DO NOTHING;

-- Read-only Embraco controller fixture for Issue #729. The temperature/control
-- engineering scale intentionally remains unverified: those samples persist raw
-- values with NULL engineering values and quality=unknown.
WITH samples AS (
    SELECT generate_series(0, 60) AS n
), controller_history AS (
    SELECT
        '72900001-0000-4000-8000-' || lpad(n::text, 12, '0') AS event_id,
        'edge-01' AS node_id,
        CURRENT_TIMESTAMP - INTERVAL '60 minutes' + n * INTERVAL '60 seconds' AS captured_at,
        'compressor.speed' AS metric,
        CASE WHEN ((n / 10) % 2) = 0 THEN 4500.0 ELSE 0.0 END AS value,
        'rpm' AS unit,
        'valid' AS quality,
        'embraco-sync' AS source,
        'EMBRACO-2' AS equipment_id,
        '2-compressor-speed' AS channel_id,
        NULL::text AS alarm,
        CASE WHEN ((n / 10) % 2) = 0 THEN 4500 ELSE 0 END AS raw_value,
        NULL::bigint AS raw_status
    FROM samples
    UNION ALL
    SELECT
        '72900002-0000-4000-8000-' || lpad(n::text, 12, '0'),
        'edge-01',
        CURRENT_TIMESTAMP - INTERVAL '60 minutes' + n * INTERVAL '60 seconds',
        'refrigeration.control_state',
        CASE WHEN ((n / 10) % 2) = 0 THEN 5.0 ELSE 0.0 END,
        'state',
        'valid',
        'embraco-sync',
        'EMBRACO-2',
        '2-control-state',
        NULL::text,
        CASE WHEN ((n / 10) % 2) = 0 THEN 5 ELSE 0 END,
        NULL::bigint
    FROM samples
    UNION ALL
    SELECT
        '72900003-0000-4000-8000-' || lpad(n::text, 12, '0'),
        'edge-01',
        CURRENT_TIMESTAMP - INTERVAL '60 minutes' + n * INTERVAL '60 seconds',
        'controller.relay_state_bits',
        CASE WHEN ((n / 10) % 2) = 0 THEN 1.0 ELSE 0.0 END,
        'bitfield',
        'valid',
        'embraco-sync',
        'EMBRACO-2',
        '2-relay-state-bits',
        NULL::text,
        CASE WHEN ((n / 10) % 2) = 0 THEN 1 ELSE 0 END,
        NULL::bigint
    FROM samples
    UNION ALL
    SELECT
        '72900004-0000-4000-8000-' || lpad(n::text, 12, '0'),
        'edge-01',
        CURRENT_TIMESTAMP - INTERVAL '60 minutes' + n * INTERVAL '60 seconds',
        'controller.alarm_state_bits',
        0.0,
        'bitfield',
        'valid',
        'embraco-sync',
        'EMBRACO-2',
        '2-alarm-state-bits',
        NULL::text,
        0,
        NULL::bigint
    FROM samples
)
INSERT INTO telemetry_samples (
    event_id, node_id, captured_at, metric, value, unit, quality, source,
    equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload,
    raw_payload_retained, received_at
)
SELECT
    event_id, node_id, captured_at, metric, value, unit, quality, source,
    equipment_id, channel_id, alarm, raw_value, raw_status,
    '{"fixture":"issue-729-embraco","stale_after_seconds":90}'::jsonb,
    TRUE, captured_at
FROM controller_history
ON CONFLICT (event_id) DO NOTHING;

INSERT INTO telemetry_samples (
    event_id, node_id, captured_at, metric, value, unit, quality, source,
    equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload,
    raw_payload_retained, received_at
) VALUES
    ('72900101-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.cabinet', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-cabinet-temperature', NULL, 82, NULL,
     '{"fixture":"issue-729-embraco","scale":"unverified","stale_after_seconds":90}'::jsonb, TRUE, CURRENT_TIMESTAMP),
    ('72900102-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.evaporator', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-evaporator-temperature', NULL, 41, NULL,
     '{"fixture":"issue-729-embraco","scale":"unverified","stale_after_seconds":90}'::jsonb, TRUE, CURRENT_TIMESTAMP),
    ('72900103-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.condenser', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-condenser-temperature', NULL, 365, NULL,
     '{"fixture":"issue-729-embraco","scale":"unverified","stale_after_seconds":90}'::jsonb, TRUE, CURRENT_TIMESTAMP),
    ('72900104-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'refrigeration.setpoint', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-setpoint', NULL, 20, NULL,
     '{"fixture":"issue-729-embraco","scale":"unverified","stale_after_seconds":90}'::jsonb, TRUE, CURRENT_TIMESTAMP),
    ('72900105-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'refrigeration.hysteresis', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-hysteresis', NULL, 10, NULL,
     '{"fixture":"issue-729-embraco","scale":"unverified","stale_after_seconds":90}'::jsonb, TRUE, CURRENT_TIMESTAMP)
ON CONFLICT (event_id) DO NOTHING;

INSERT INTO telemetry_latest (
    sample_id, event_id, node_id, captured_at, metric, value, unit, quality,
    source, equipment_id, channel_id, alarm, raw_value, raw_status,
    stale_after_seconds, received_at
) VALUES
    (729010, '72901001-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'compressor.speed', 4500.0, 'rpm', 'valid', 'embraco-sync', 'EMBRACO-2',
     '2-compressor-speed', NULL, 4500, NULL, 90.0, CURRENT_TIMESTAMP),
    (729011, '72901002-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'refrigeration.control_state', 5.0, 'state', 'valid', 'embraco-sync', 'EMBRACO-2',
     '2-control-state', NULL, 5, NULL, 90.0, CURRENT_TIMESTAMP),
    (729012, '72901003-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'controller.relay_state_bits', 1.0, 'bitfield', 'valid', 'embraco-sync', 'EMBRACO-2',
     '2-relay-state-bits', NULL, 1, NULL, 90.0, CURRENT_TIMESTAMP),
    (729013, '72901004-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'controller.alarm_state_bits', 0.0, 'bitfield', 'valid', 'embraco-sync', 'EMBRACO-2',
     '2-alarm-state-bits', NULL, 0, NULL, 90.0, CURRENT_TIMESTAMP),
    (729014, '72901005-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.cabinet', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-cabinet-temperature', NULL, 82, NULL, 90.0, CURRENT_TIMESTAMP),
    (729015, '72901006-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.evaporator', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-evaporator-temperature', NULL, 41, NULL, 90.0, CURRENT_TIMESTAMP),
    (729016, '72901007-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'temperature.condenser', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-condenser-temperature', NULL, 365, NULL, 90.0, CURRENT_TIMESTAMP),
    (729017, '72901008-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'refrigeration.setpoint', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-setpoint', NULL, 20, NULL, 90.0, CURRENT_TIMESTAMP),
    (729018, '72901009-0000-4000-8000-000000000001', 'edge-01', CURRENT_TIMESTAMP,
     'refrigeration.hysteresis', NULL, 'degC', 'unknown', 'embraco-sync', 'EMBRACO-2',
     '2-hysteresis', NULL, 10, NULL, 90.0, CURRENT_TIMESTAMP)
ON CONFLICT (node_id, equipment_id, channel_id, metric) DO UPDATE SET
    sample_id = EXCLUDED.sample_id,
    event_id = EXCLUDED.event_id,
    captured_at = EXCLUDED.captured_at,
    value = EXCLUDED.value,
    unit = EXCLUDED.unit,
    quality = EXCLUDED.quality,
    source = EXCLUDED.source,
    alarm = EXCLUDED.alarm,
    raw_value = EXCLUDED.raw_value,
    raw_status = EXCLUDED.raw_status,
    stale_after_seconds = EXCLUDED.stale_after_seconds,
    received_at = EXCLUDED.received_at;
SQL
}

collect_evidence() {
  if [[ "$STACK_STARTED" != "1" ]]; then
    return 0
  fi

  compose ps --all >"$EVIDENCE_DIR/compose-ps.txt" 2>&1 || true
  compose logs --no-color >"$EVIDENCE_DIR/central-stack.log" 2>&1 || true

  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/postgresql-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT node_id, display_name, state, last_seen_at
FROM central_nodes
WHERE node_id = 'kk2-acceptance';

SELECT node_id, channel_id, metric, value, unit, quality, captured_at
FROM telemetry_samples
WHERE node_id = 'kk2-acceptance'
ORDER BY channel_id;

SELECT id, code, name, node_id, version, lifecycle_status, deleted_at
FROM refrigeration_equipment
ORDER BY created_at;

SELECT equipment_id, slot_key, channel_id, label, side, shelf, position, version, unbound_at
FROM refrigeration_sensor_bindings
ORDER BY equipment_id, bound_at;

SELECT equipment_id, version, image_id, json_array_length(placements) AS placement_count
FROM refrigeration_layout_drafts
ORDER BY equipment_id;

SELECT equipment_id, revision, source_draft_version, image_id,
       json_array_length(placements) AS placement_count, published_by, published_at
FROM refrigeration_layout_revisions
ORDER BY equipment_id, revision;

SELECT equipment_id, original_filename, media_type, size_bytes, width_px, height_px,
       storage_key, created_by, created_at
FROM equipment_images
ORDER BY created_at;
SQL

  compose run --rm --no-deps --entrypoint /bin/sh minio-init -ec '
    mc alias set acceptance http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc anonymous get "acceptance/$OBJECT_STORAGE_BUCKET"
    mc ls --recursive "acceptance/$OBJECT_STORAGE_BUCKET"
  ' >"$EVIDENCE_DIR/minio-state.txt" 2>&1 || true
}

cleanup() {
  if [[ "$STACK_STARTED" == "1" && "${KEEP_ACCEPTANCE_STACK:-0}" != "1" ]]; then
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  collect_evidence
  cleanup
  printf '\nAcceptance evidence: %s\n' "$EVIDENCE_DIR"
  exit "$status"
}
trap on_exit EXIT

for command in docker npm curl; do
  if ! command -v "$command" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "$command" >&2
    exit 1
  fi
done

cd "$ROOT_DIR"

npm install --no-audit --no-fund
if [[ -n "${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-}" ]]; then
  if [[ ! -x "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" ]]; then
    printf 'Configured Playwright browser is not executable: %s\n' "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH" >&2
    exit 1
  fi
  printf 'Using preinstalled Playwright browser: %s\n' "$PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"
  npx playwright install ffmpeg
elif [[ "${PLAYWRIGHT_INSTALL_WITH_DEPS:-0}" == "1" ]]; then
  npx playwright install --with-deps chromium
else
  npx playwright install chromium
fi

compose up --detach --build
STACK_STARTED=1

ready=0
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error \
    "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null 2>&1 && \
    curl --fail --silent --show-error \
      "http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT/minio/health/live" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done

if [[ "$ready" != "1" ]]; then
  printf 'Central acceptance stack did not become ready.\n' >&2
  exit 1
fi

seed_camera_scoped_fixtures

npm run build
npm run test:e2e:production
