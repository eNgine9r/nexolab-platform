#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
PROJECT_NAME="nexolab-reports-acceptance"
API_PORT="${NEXOLAB_REPORTS_API_PORT:-8084}"
MQTT_PORT="${NEXOLAB_REPORTS_MQTT_PORT:-1886}"
FRONTEND_PORT="${NEXOLAB_REPORTS_FRONTEND_PORT:-3104}"
OBJECT_STORAGE_PORT="${NEXOLAB_REPORTS_OBJECT_STORAGE_PORT:-9014}"
OBJECT_STORAGE_CONSOLE_PORT="${NEXOLAB_REPORTS_OBJECT_STORAGE_CONSOLE_PORT:-9015}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"
FRONTEND_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-frontend.log"
SERVICE_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-services.log"
EVIDENCE_DIR="$ROOT_DIR/test-results-reports"
FRONTEND_PID=""

POSTGRES_PASSWORD="reports-acceptance-postgres"
MINIO_ROOT_USER="reports-acceptance-minio"
MINIO_ROOT_PASSWORD="reports-acceptance-minio-secret"
JWT_SECRET="reports-browser-acceptance-secret-with-at-least-thirty-two-bytes"
JWT_ISSUER="https://auth.nexolab.local/reports-acceptance"
JWT_AUDIENCE="nexolab-reports-acceptance"
JWT_PROVIDER="reports-acceptance"

ORGANIZATION_A="00000000-0000-0000-0000-000000000001"
ORGANIZATION_B="00000000-0000-0000-0000-000000000002"
ENGINEER_A_ID="20000000-0000-0000-0000-000000000011"
MANAGER_A_ID="20000000-0000-0000-0000-000000000012"
MANAGER_B_ID="20000000-0000-0000-0000-000000000013"
VIEWER_A_ID="20000000-0000-0000-0000-000000000014"
ENGINEER_A_MEMBERSHIP="30000000-0000-0000-0000-000000000011"
MANAGER_A_MEMBERSHIP="30000000-0000-0000-0000-000000000012"
MANAGER_B_MEMBERSHIP="30000000-0000-0000-0000-000000000013"
VIEWER_A_MEMBERSHIP="30000000-0000-0000-0000-000000000014"
ENGINEER_A_SUBJECT="engineer-a-reports-acceptance"
MANAGER_A_SUBJECT="manager-a-reports-acceptance"
MANAGER_B_SUBJECT="manager-b-reports-acceptance"
VIEWER_A_SUBJECT="viewer-a-reports-acceptance"
COMPLETED_SESSION_ID="40000000-0000-0000-0000-000000000001"
RUNNING_SESSION_ID="40000000-0000-0000-0000-000000000002"
BINDING_ID="50000000-0000-0000-0000-000000000001"
SNAPSHOT_ID="60000000-0000-0000-0000-000000000001"
STAGE_ID="70000000-0000-0000-0000-000000000001"
TELEMETRY_EVENT_ID="80000000-0000-0000-0000-000000000001"
ALERT_RULE_ID="90000000-0000-0000-0000-000000000001"
ALERT_RULE_VERSION_ID="91000000-0000-0000-0000-000000000001"
ALERT_ID="92000000-0000-0000-0000-000000000001"
ALERT_TRIGGER_ID="93000000-0000-0000-0000-000000000001"
ALERT_ACK_ID="93000000-0000-0000-0000-000000000002"
ALERT_RESOLVE_ID="93000000-0000-0000-0000-000000000003"
ALERT_CLOSE_ID="93000000-0000-0000-0000-000000000004"

export POSTGRES_DB="nexolab"
export POSTGRES_USER="nexolab"
export POSTGRES_PASSWORD
export MINIO_ROOT_USER
export MINIO_ROOT_PASSWORD
export OBJECT_STORAGE_BUCKET="nexolab-reports-acceptance"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="$API_PORT"
export CENTRAL_MQTT_PORT="$MQTT_PORT"
export CENTRAL_OBJECT_STORAGE_PORT="$OBJECT_STORAGE_PORT"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="$OBJECT_STORAGE_CONSOLE_PORT"
export MQTT_TOPIC="nexolab/telemetry"
export MQTT_CLIENT_ID="nexolab-reports-browser-acceptance"
export CORS_ALLOWED_ORIGINS="$FRONTEND_BASE_URL"
export CORS_ALLOW_CREDENTIALS="false"
export AUTH_MODE="jwt"
export AUTH_DEFAULT_ORGANIZATION_ID="$ORGANIZATION_A"
export AUTH_JWT_PUBLIC_KEY="$JWT_SECRET"
export AUTH_JWT_ALGORITHM="HS256"
export AUTH_JWT_ISSUER="$JWT_ISSUER"
export AUTH_JWT_AUDIENCE="$JWT_AUDIENCE"
export AUTH_JWT_PROVIDER="$JWT_PROVIDER"
export RETENTION_ENABLED="false"
export OBJECT_STORAGE_PUBLIC_ENDPOINT_URL="http://127.0.0.1:${OBJECT_STORAGE_PORT}"
export ACCEPTANCE_MQTT_VOLUME_NAME="${PROJECT_NAME}-mqtt-data"
export ACCEPTANCE_POSTGRES_VOLUME_NAME="${PROJECT_NAME}-postgres-data"
export ACCEPTANCE_OBJECT_STORAGE_VOLUME_NAME="${PROJECT_NAME}-object-storage-data"
export ACCEPTANCE_NETWORK_NAME="${PROJECT_NAME}-network"

compose() {
  docker compose \
    --project-name "$PROJECT_NAME" \
    -f "$COMPOSE_DIR/compose.central.yaml" \
    -f "$COMPOSE_DIR/compose.browser-acceptance.yaml" \
    "$@"
}

cleanup() {
  local status=$?
  set +e
  if [[ -n "$FRONTEND_PID" ]]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
    wait "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  compose ps --all >"$EVIDENCE_DIR/compose-ps.log" 2>&1 || true
  compose logs --no-color telemetry-service postgres mqtt >"$SERVICE_LOG" 2>&1 || true
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ $status -ne 0 ]]; then
    echo "Reports browser acceptance failed. Frontend log:" >&2
    tail -n 180 "$FRONTEND_LOG" >&2 || true
    echo "Service log:" >&2
    tail -n 240 "$SERVICE_LOG" >&2 || true
  fi
  exit "$status"
}
trap cleanup EXIT

wait_for_url() {
  local url=$1
  local label=$2
  for _ in $(seq 1 90); do
    if curl --fail --silent --show-error "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "Timed out waiting for ${label}: ${url}" >&2
  return 1
}

jwt_token() {
  local subject=$1
  local email=$2
  local display_name=$3
  python3 - "$JWT_SECRET" "$JWT_ISSUER" "$JWT_AUDIENCE" "$subject" "$email" "$display_name" <<'PY'
import base64
import hashlib
import hmac
import json
import sys
import time

secret, issuer, audience, subject, email, display_name = sys.argv[1:]

def encode(value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

now = int(time.time())
header = {"alg": "HS256", "typ": "JWT"}
payload = {
    "iss": issuer,
    "aud": audience,
    "sub": subject,
    "email": email,
    "name": display_name,
    "iat": now,
    "nbf": now - 5,
    "exp": now + 3600,
}
unsigned = f"{encode(header)}.{encode(payload)}"
signature = hmac.new(secret.encode("utf-8"), unsigned.encode("ascii"), hashlib.sha256).digest()
print(f"{unsigned}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}")
PY
}

for command in docker npm curl python3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command is missing: $command" >&2
    exit 1
  fi
done

rm -rf "$EVIDENCE_DIR" "$ROOT_DIR/playwright-report-reports"
mkdir -p "$EVIDENCE_DIR"
compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up -d --build mqtt postgres minio minio-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "telemetry service"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  ('$ORGANIZATION_A', 'reports-org-a', 'Reports Acceptance Organization A', true),
  ('$ORGANIZATION_B', 'reports-org-b', 'Reports Acceptance Organization B', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (
  id, provider, subject, email, display_name, is_active, last_authenticated_at
)
VALUES
  ('$ENGINEER_A_ID', '$JWT_PROVIDER', '$ENGINEER_A_SUBJECT', 'engineer-a-reports@nexolab.local', 'Engineer A Reports', true, now()),
  ('$MANAGER_A_ID', '$JWT_PROVIDER', '$MANAGER_A_SUBJECT', 'manager-a-reports@nexolab.local', 'Manager A Reports', true, now()),
  ('$MANAGER_B_ID', '$JWT_PROVIDER', '$MANAGER_B_SUBJECT', 'manager-b-reports@nexolab.local', 'Manager B Reports', true, now()),
  ('$VIEWER_A_ID', '$JWT_PROVIDER', '$VIEWER_A_SUBJECT', 'viewer-a-reports@nexolab.local', 'Viewer A Reports', true, now())
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email,
    display_name = EXCLUDED.display_name,
    is_active = true,
    last_authenticated_at = EXCLUDED.last_authenticated_at;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('$ENGINEER_A_MEMBERSHIP', '$ORGANIZATION_A', '$ENGINEER_A_ID', true),
  ('$MANAGER_A_MEMBERSHIP', '$ORGANIZATION_A', '$MANAGER_A_ID', true),
  ('$MANAGER_B_MEMBERSHIP', '$ORGANIZATION_B', '$MANAGER_B_ID', true),
  ('$VIEWER_A_MEMBERSHIP', '$ORGANIZATION_A', '$VIEWER_A_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('$ENGINEER_A_MEMBERSHIP', 'engineer', 'reports-browser-acceptance'),
  ('$MANAGER_A_MEMBERSHIP', 'laboratory_manager', 'reports-browser-acceptance'),
  ('$MANAGER_B_MEMBERSHIP', 'laboratory_manager', 'reports-browser-acceptance'),
  ('$VIEWER_A_MEMBERSHIP', 'viewer', 'reports-browser-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;

INSERT INTO test_sessions (
  id, organization_id, create_idempotency_key, session_number, node_id, state,
  title, test_object, standard, method, active_config_snapshot_id,
  started_at, completed_at, created_at, updated_at
)
VALUES
  (
    '$COMPLETED_SESSION_ID', '$ORGANIZATION_A', 'reports-completed-create',
    'NX-REPORTS-0001', 'edge-01', 'completed', 'Reports completed session',
    'K106', 'ISO 23953', 'temperature distribution', NULL,
    '2026-07-26T12:00:00Z', '2026-07-26T14:00:00Z', now(), now()
  ),
  (
    '$RUNNING_SESSION_ID', '$ORGANIZATION_A', 'reports-running-create',
    'NX-REPORTS-0002', 'edge-01', 'running', 'Reports running session',
    'K106', 'ISO 23953', 'temperature distribution', NULL,
    '2026-07-26T15:00:00Z', NULL, now(), now()
  );

INSERT INTO session_channel_bindings (
  id, session_id, node_id, equipment_id, channel_id, metric, unit,
  binding_metadata, activated_at, released_at, created_at
)
VALUES (
  '$BINDING_ID', '$COMPLETED_SESSION_ID', 'edge-01', 'K106', '106-03',
  'temperature.probe', 'degC', '{"position":"front-left"}',
  '2026-07-26T12:00:00Z', '2026-07-26T14:00:00Z', now()
);

INSERT INTO session_config_snapshots (
  id, session_id, version, source, payload, content_sha256, created_by,
  captured_at, created_at
)
VALUES (
  '$SNAPSHOT_ID', '$COMPLETED_SESSION_ID', 1, 'session_start',
  json_build_object(
    'bindings', json_build_array(
      json_build_object(
        'id', '$BINDING_ID',
        'node_id', 'edge-01',
        'equipment_id', 'K106',
        'channel_id', '106-03',
        'metric', 'temperature.probe'
      )
    )
  ),
  repeat('a', 64), '$ENGINEER_A_SUBJECT', '2026-07-26T12:00:00Z', now()
);

UPDATE test_sessions
SET active_config_snapshot_id = '$SNAPSHOT_ID'
WHERE id = '$COMPLETED_SESSION_ID';

INSERT INTO session_stages (
  id, session_id, sequence_index, stage_type, name, description,
  planned_duration_seconds, entered_at, exited_at, created_at
)
VALUES (
  '$STAGE_ID', '$COMPLETED_SESSION_ID', 0, 'main_test', 'Main Test',
  'Controlled reports acceptance stage', 7200,
  '2026-07-26T12:00:00Z', '2026-07-26T14:00:00Z', now()
);

INSERT INTO telemetry_samples (
  event_id, node_id, captured_at, metric, value, unit, quality, source,
  equipment_id, channel_id, alarm, raw_value, raw_status, raw_payload,
  raw_payload_retained, received_at
)
VALUES (
  '$TELEMETRY_EVENT_ID', 'edge-01', '2026-07-26T12:10:00Z',
  'temperature.probe', 3.75, 'degC', 'valid', 'reports-browser-acceptance',
  'K106', '106-03', NULL, 375, 0, '{"register":375}', true,
  '2026-07-26T12:10:01Z'
);

INSERT INTO telemetry_session_contexts (
  telemetry_event_id, session_id, stage_id, binding_id, config_snapshot_id,
  captured_at, attributed_at, resolver_version
)
VALUES (
  '$TELEMETRY_EVENT_ID', '$COMPLETED_SESSION_ID', '$STAGE_ID', '$BINDING_ID',
  '$SNAPSHOT_ID', '2026-07-26T12:10:00Z', '2026-07-26T12:10:01Z',
  'snapshot-timeline-v1'
);

INSERT INTO alert_rules (
  id, organization_id, name, description, enabled, severity, node_id,
  equipment_id, channel_id, metric, session_id, current_version, created_by,
  created_at, updated_at
)
VALUES (
  '$ALERT_RULE_ID', '$ORGANIZATION_A', 'Reports acceptance temperature',
  'Lifecycle evidence for report export', true, 'warning', 'edge-01',
  'K106', '106-03', 'temperature.probe', '$COMPLETED_SESSION_ID', 1,
  '$ENGINEER_A_SUBJECT', '2026-07-26T12:00:00Z', '2026-07-26T12:00:00Z'
);

INSERT INTO alert_rule_versions (
  id, rule_id, version, condition, trigger_threshold, clear_threshold,
  minimum_duration_seconds, clear_duration_seconds, debounce_seconds,
  cooldown_seconds, configuration, created_by, created_at
)
VALUES (
  '$ALERT_RULE_VERSION_ID', '$ALERT_RULE_ID', 1, 'threshold_high', 8, 7,
  60, 30, 0, 120, '{"standard":"ISO 23953"}', '$ENGINEER_A_SUBJECT',
  '2026-07-26T12:00:00Z'
);

INSERT INTO alert_instances (
  id, organization_id, rule_id, rule_version_id, resource_key, node_id,
  equipment_id, channel_id, metric, state, severity, trigger_value,
  trigger_threshold, clear_threshold, maximum_deviation, first_event_id,
  last_event_id, session_id, stage_id, binding_id, context, triggered_at,
  acknowledged_at, resolved_at, closed_at, lock_version, created_at, updated_at
)
VALUES (
  '$ALERT_ID', '$ORGANIZATION_A', '$ALERT_RULE_ID', '$ALERT_RULE_VERSION_ID',
  'edge-01|K106|106-03|temperature.probe', 'edge-01', 'K106', '106-03',
  'temperature.probe', 'closed', 'warning', 8.5, 8, 7, 1.2,
  '$TELEMETRY_EVENT_ID', '$TELEMETRY_EVENT_ID', '$COMPLETED_SESSION_ID',
  '$STAGE_ID', '$BINDING_ID', '{"acceptance":true}',
  '2026-07-26T12:10:00Z', '2026-07-26T12:11:00Z',
  '2026-07-26T12:20:00Z', '2026-07-26T12:21:00Z', 4,
  '2026-07-26T12:10:00Z', '2026-07-26T12:21:00Z'
);

INSERT INTO alert_transitions (
  id, alert_id, event_type, previous_state, next_state, actor_id, actor_source,
  reason, idempotency_key, payload, occurred_at, inserted_at
)
VALUES
  (
    '$ALERT_TRIGGER_ID', '$ALERT_ID', 'alert_triggered', NULL, 'active',
    'alert-rule-engine', 'system', 'Threshold duration met',
    'reports-alert-triggered', '{}', '2026-07-26T12:10:00Z', now()
  ),
  (
    '$ALERT_ACK_ID', '$ALERT_ID', 'alert_acknowledged', 'active', 'acknowledged',
    '$ENGINEER_A_SUBJECT', '$JWT_PROVIDER', 'Operator reviewed evidence',
    'reports-alert-acknowledged', '{}', '2026-07-26T12:11:00Z', now()
  ),
  (
    '$ALERT_RESOLVE_ID', '$ALERT_ID', 'alert_resolved', 'acknowledged', 'resolved',
    'alert-rule-engine', 'system', 'Clear duration met',
    'reports-alert-resolved', '{}', '2026-07-26T12:20:00Z', now()
  ),
  (
    '$ALERT_CLOSE_ID', '$ALERT_ID', 'alert_closed', 'resolved', 'closed',
    '$ENGINEER_A_SUBJECT', '$JWT_PROVIDER', 'Evidence finalized',
    'reports-alert-closed', '{}', '2026-07-26T12:21:00Z', now()
  );
SQL

ENGINEER_A_TOKEN="$(jwt_token "$ENGINEER_A_SUBJECT" 'engineer-a-reports@nexolab.local' 'Engineer A Reports')"
MANAGER_A_TOKEN="$(jwt_token "$MANAGER_A_SUBJECT" 'manager-a-reports@nexolab.local' 'Manager A Reports')"
MANAGER_B_TOKEN="$(jwt_token "$MANAGER_B_SUBJECT" 'manager-b-reports@nexolab.local' 'Manager B Reports')"
VIEWER_A_TOKEN="$(jwt_token "$VIEWER_A_SUBJECT" 'viewer-a-reports@nexolab.local' 'Viewer A Reports')"

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_A"
export NEXT_TELEMETRY_DISABLED="1"

rm -f "$FRONTEND_LOG"
npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/reports" "Next.js reports workspace"

export NEXOLAB_REPORTS_BASE_URL="$FRONTEND_BASE_URL"
export NEXOLAB_REPORTS_API_BASE_URL="$API_BASE_URL"
export NEXOLAB_REPORTS_ORGANIZATION_A="$ORGANIZATION_A"
export NEXOLAB_REPORTS_ORGANIZATION_B="$ORGANIZATION_B"
export NEXOLAB_REPORTS_ENGINEER_A_TOKEN="$ENGINEER_A_TOKEN"
export NEXOLAB_REPORTS_MANAGER_A_TOKEN="$MANAGER_A_TOKEN"
export NEXOLAB_REPORTS_MANAGER_B_TOKEN="$MANAGER_B_TOKEN"
export NEXOLAB_REPORTS_VIEWER_A_TOKEN="$VIEWER_A_TOKEN"
export NEXOLAB_REPORTS_COMPLETED_SESSION_ID="$COMPLETED_SESSION_ID"
export NEXOLAB_REPORTS_RUNNING_SESSION_ID="$RUNNING_SESSION_ID"
export NEXOLAB_REPORTS_TELEMETRY_EVENT_ID="$TELEMETRY_EVENT_ID"
export NEXOLAB_REPORTS_ALERT_TRANSITION_ID="$ALERT_ACK_ID"

npm run test:e2e:reports

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
DO \$\$
DECLARE
  report_count integer;
  artifact_count integer;
  generation_audit_count integer;
  download_audit_count integer;
BEGIN
  SELECT count(*) INTO report_count
  FROM test_report_versions
  WHERE organization_id = '$ORGANIZATION_A'
    AND session_id = '$COMPLETED_SESSION_ID';
  IF report_count <> 3 THEN
    RAISE EXCEPTION 'expected three immutable report versions, found %', report_count;
  END IF;

  SELECT count(*) INTO artifact_count
  FROM test_report_artifacts a
  JOIN test_report_versions r ON r.id = a.report_id
  WHERE r.organization_id = '$ORGANIZATION_A';
  IF artifact_count <> 12 THEN
    RAISE EXCEPTION 'expected twelve immutable report artifacts, found %', artifact_count;
  END IF;

  SELECT count(*) INTO generation_audit_count
  FROM security_audit_events
  WHERE organization_id = '$ORGANIZATION_A'
    AND action = 'report.generated';
  IF generation_audit_count <> 3 THEN
    RAISE EXCEPTION 'expected three report generation audit events, found %', generation_audit_count;
  END IF;

  SELECT count(*) INTO download_audit_count
  FROM security_audit_events
  WHERE organization_id = '$ORGANIZATION_A'
    AND action = 'report.artifact.downloaded';
  IF download_audit_count < 4 THEN
    RAISE EXCEPTION 'expected report artifact download audit evidence, found %', download_audit_count;
  END IF;

  BEGIN
    UPDATE test_report_versions
    SET generated_by = 'forbidden-mutation'
    WHERE organization_id = '$ORGANIZATION_A';
    RAISE EXCEPTION 'report version update unexpectedly succeeded';
  EXCEPTION WHEN SQLSTATE '55000' THEN
    NULL;
  END;

  BEGIN
    DELETE FROM test_report_artifacts
    WHERE report_id IN (
      SELECT id FROM test_report_versions WHERE organization_id = '$ORGANIZATION_A'
    );
    RAISE EXCEPTION 'report artifact delete unexpectedly succeeded';
  EXCEPTION WHEN SQLSTATE '55000' THEN
    NULL;
  END;
END
\$\$;
SQL

compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -P pager=off <<SQL >"$EVIDENCE_DIR/database-evidence.txt"
SELECT id, organization_id, session_id, version, source_sha256, manifest_sha256,
       generator_version, generated_by, generated_at
FROM test_report_versions
ORDER BY version;

SELECT r.version, a.name, a.media_type, a.sha256, a.size_bytes, a.row_count
FROM test_report_artifacts a
JOIN test_report_versions r ON r.id = a.report_id
ORDER BY r.version, a.name;

SELECT action, actor_subject, entity_type, entity_id, occurred_at
FROM security_audit_events
WHERE action IN ('report.generated', 'report.artifact.downloaded')
ORDER BY occurred_at, id;
SQL

cp "$FRONTEND_LOG" "$EVIDENCE_DIR/frontend.log"
echo "Reports browser acceptance completed successfully."
