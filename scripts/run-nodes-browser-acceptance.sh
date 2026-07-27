#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$ROOT_DIR/infrastructure/compose"
PROJECT_NAME="nexolab-nodes-acceptance"
API_PORT="${NEXOLAB_NODES_API_PORT:-8086}"
MQTT_PORT="${NEXOLAB_NODES_MQTT_PORT:-1888}"
FRONTEND_PORT="${NEXOLAB_NODES_FRONTEND_PORT:-3106}"
OBJECT_STORAGE_PORT="${NEXOLAB_NODES_OBJECT_STORAGE_PORT:-9016}"
OBJECT_STORAGE_CONSOLE_PORT="${NEXOLAB_NODES_OBJECT_STORAGE_CONSOLE_PORT:-9017}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
FRONTEND_BASE_URL="http://127.0.0.1:${FRONTEND_PORT}"
FRONTEND_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-frontend.log"
SERVICE_LOG="${TMPDIR:-/tmp}/${PROJECT_NAME}-services.log"
EVIDENCE_DIR="$ROOT_DIR/test-results-nodes"
FRONTEND_PID=""

POSTGRES_PASSWORD="nodes-acceptance-postgres"
MINIO_ROOT_USER="nodes-acceptance-minio"
MINIO_ROOT_PASSWORD="nodes-acceptance-minio-secret"
JWT_SECRET="nodes-browser-acceptance-secret-with-at-least-thirty-two-bytes"
JWT_ISSUER="https://auth.nexolab.local/nodes-acceptance"
JWT_AUDIENCE="nexolab-nodes-acceptance"
JWT_PROVIDER="nodes-acceptance"

ORGANIZATION_A="00000000-0000-0000-0000-000000000001"
ORGANIZATION_B="00000000-0000-0000-0000-000000000002"
MANAGER_A_ID="21000000-0000-0000-0000-000000000011"
MANAGER_B_ID="21000000-0000-0000-0000-000000000012"
ENGINEER_A_ID="21000000-0000-0000-0000-000000000013"
VIEWER_A_ID="21000000-0000-0000-0000-000000000014"
MANAGER_A_MEMBERSHIP="31000000-0000-0000-0000-000000000011"
MANAGER_B_MEMBERSHIP="31000000-0000-0000-0000-000000000012"
ENGINEER_A_MEMBERSHIP="31000000-0000-0000-0000-000000000013"
VIEWER_A_MEMBERSHIP="31000000-0000-0000-0000-000000000014"
MANAGER_A_SUBJECT="manager-a-nodes-acceptance"
MANAGER_B_SUBJECT="manager-b-nodes-acceptance"
ENGINEER_A_SUBJECT="engineer-a-nodes-acceptance"
VIEWER_A_SUBJECT="viewer-a-nodes-acceptance"

export POSTGRES_DB="nexolab"
export POSTGRES_USER="nexolab"
export POSTGRES_PASSWORD
export MINIO_ROOT_USER
export MINIO_ROOT_PASSWORD
export OBJECT_STORAGE_BUCKET="nexolab-nodes-acceptance"
export CENTRAL_BIND_ADDRESS="127.0.0.1"
export CENTRAL_API_PORT="$API_PORT"
export CENTRAL_MQTT_PORT="$MQTT_PORT"
export CENTRAL_OBJECT_STORAGE_PORT="$OBJECT_STORAGE_PORT"
export CENTRAL_OBJECT_STORAGE_CONSOLE_PORT="$OBJECT_STORAGE_CONSOLE_PORT"
export MQTT_TOPIC="nexolab/telemetry"
export MQTT_CLIENT_ID="nexolab-nodes-browser-acceptance"
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
export TELEMETRY_SERVICE_IMAGE="nexolab-telemetry-service:nodes-acceptance"
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
  compose exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
    >"$EVIDENCE_DIR/nodes-database-state.txt" 2>&1 <<'SQL' || true
\pset pager off
SELECT organization_id, node_id, display_name, state, state_reason,
       clock_status, last_seen_at, created_by, created_at, updated_at
FROM central_nodes
ORDER BY organization_id, node_id;

SELECT n.organization_id, n.node_id, c.generation, c.secret_fingerprint,
       c.issued_by, c.issued_at, c.revoked_at, c.revoked_by, c.revocation_reason
FROM central_node_credentials c
JOIN central_nodes n ON n.id = c.node_record_id
ORDER BY n.organization_id, n.node_id, c.generation;

SELECT organization_id, action, entity_type, entity_id, actor_subject,
       actor_roles, reason, occurred_at
FROM security_audit_events
WHERE entity_type = 'central_node'
ORDER BY occurred_at, id;
SQL
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  if [[ $status -ne 0 ]]; then
    echo "Nodes browser acceptance failed. Frontend log:" >&2
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

rm -rf "$EVIDENCE_DIR" "$ROOT_DIR/playwright-report-nodes"
mkdir -p "$EVIDENCE_DIR"
compose down --volumes --remove-orphans >/dev/null 2>&1 || true
compose up -d --build mqtt postgres minio minio-init telemetry-migrate telemetry-service
wait_for_url "$API_BASE_URL/health/ready" "telemetry service"

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
INSERT INTO security_organizations (id, slug, name, is_active)
VALUES
  ('$ORGANIZATION_A', 'nodes-org-a', 'Nodes Acceptance Organization A', true),
  ('$ORGANIZATION_B', 'nodes-org-b', 'Nodes Acceptance Organization B', true)
ON CONFLICT (id) DO UPDATE
SET slug = EXCLUDED.slug, name = EXCLUDED.name, is_active = true;

INSERT INTO security_identities (
  id, provider, subject, email, display_name, is_active, last_authenticated_at
)
VALUES
  ('$MANAGER_A_ID', '$JWT_PROVIDER', '$MANAGER_A_SUBJECT', 'manager-a-nodes@nexolab.local', 'Manager A Nodes', true, now()),
  ('$MANAGER_B_ID', '$JWT_PROVIDER', '$MANAGER_B_SUBJECT', 'manager-b-nodes@nexolab.local', 'Manager B Nodes', true, now()),
  ('$ENGINEER_A_ID', '$JWT_PROVIDER', '$ENGINEER_A_SUBJECT', 'engineer-a-nodes@nexolab.local', 'Engineer A Nodes', true, now()),
  ('$VIEWER_A_ID', '$JWT_PROVIDER', '$VIEWER_A_SUBJECT', 'viewer-a-nodes@nexolab.local', 'Viewer A Nodes', true, now())
ON CONFLICT (provider, subject) DO UPDATE
SET email = EXCLUDED.email,
    display_name = EXCLUDED.display_name,
    is_active = true,
    last_authenticated_at = EXCLUDED.last_authenticated_at;

INSERT INTO security_organization_memberships (id, organization_id, identity_id, is_active)
VALUES
  ('$MANAGER_A_MEMBERSHIP', '$ORGANIZATION_A', '$MANAGER_A_ID', true),
  ('$MANAGER_B_MEMBERSHIP', '$ORGANIZATION_B', '$MANAGER_B_ID', true),
  ('$ENGINEER_A_MEMBERSHIP', '$ORGANIZATION_A', '$ENGINEER_A_ID', true),
  ('$VIEWER_A_MEMBERSHIP', '$ORGANIZATION_A', '$VIEWER_A_ID', true)
ON CONFLICT (organization_id, identity_id) DO UPDATE SET is_active = true;

INSERT INTO security_membership_roles (membership_id, role, assigned_by)
VALUES
  ('$MANAGER_A_MEMBERSHIP', 'laboratory_manager', 'nodes-browser-acceptance'),
  ('$MANAGER_B_MEMBERSHIP', 'laboratory_manager', 'nodes-browser-acceptance'),
  ('$ENGINEER_A_MEMBERSHIP', 'engineer', 'nodes-browser-acceptance'),
  ('$VIEWER_A_MEMBERSHIP', 'viewer', 'nodes-browser-acceptance')
ON CONFLICT (membership_id, role) DO NOTHING;
SQL

MANAGER_A_TOKEN="$(jwt_token "$MANAGER_A_SUBJECT" 'manager-a-nodes@nexolab.local' 'Manager A Nodes')"
MANAGER_B_TOKEN="$(jwt_token "$MANAGER_B_SUBJECT" 'manager-b-nodes@nexolab.local' 'Manager B Nodes')"
ENGINEER_A_TOKEN="$(jwt_token "$ENGINEER_A_SUBJECT" 'engineer-a-nodes@nexolab.local' 'Engineer A Nodes')"
VIEWER_A_TOKEN="$(jwt_token "$VIEWER_A_SUBJECT" 'viewer-a-nodes@nexolab.local' 'Viewer A Nodes')"

cd "$ROOT_DIR"
export NEXT_PUBLIC_NEXOLAB_DATA_MODE="live"
export NEXT_PUBLIC_NEXOLAB_API_BASE_URL="$API_BASE_URL"
export NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:${API_PORT}/api/v1/telemetry/live"
export NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER="acceptance"
export NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID="$ORGANIZATION_A"
export NEXT_TELEMETRY_DISABLED="1"

rm -f "$FRONTEND_LOG" "$SERVICE_LOG"
npm run build >"$FRONTEND_LOG" 2>&1
npm run start -- --hostname 127.0.0.1 --port "$FRONTEND_PORT" >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!
wait_for_url "$FRONTEND_BASE_URL/nodes" "Next.js nodes workspace"

export NEXOLAB_NODES_BASE_URL="$FRONTEND_BASE_URL"
export NEXOLAB_NODES_API_BASE_URL="$API_BASE_URL"
export NEXOLAB_NODES_ORGANIZATION_A="$ORGANIZATION_A"
export NEXOLAB_NODES_ORGANIZATION_B="$ORGANIZATION_B"
export NEXOLAB_NODES_MANAGER_A_TOKEN="$MANAGER_A_TOKEN"
export NEXOLAB_NODES_MANAGER_B_TOKEN="$MANAGER_B_TOKEN"
export NEXOLAB_NODES_ENGINEER_A_TOKEN="$ENGINEER_A_TOKEN"
export NEXOLAB_NODES_VIEWER_A_TOKEN="$VIEWER_A_TOKEN"

npm run test:e2e:nodes

compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
DO \$\$
DECLARE
  org_a_nodes integer;
  org_b_nodes integer;
  credential_count integer;
  edge_one_active_credentials integer;
  edge_two_active_credentials integer;
  node_audit_count integer;
  secret_leak_count integer;
BEGIN
  SELECT count(*) INTO org_a_nodes
  FROM central_nodes
  WHERE organization_id = '$ORGANIZATION_A';
  IF org_a_nodes <> 2 THEN
    RAISE EXCEPTION 'expected two nodes for organization A, found %', org_a_nodes;
  END IF;

  SELECT count(*) INTO org_b_nodes
  FROM central_nodes
  WHERE organization_id = '$ORGANIZATION_B';
  IF org_b_nodes <> 0 THEN
    RAISE EXCEPTION 'expected no nodes for organization B, found %', org_b_nodes;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM central_nodes
    WHERE organization_id = '$ORGANIZATION_A'
      AND node_id = 'edge-01'
      AND state = 'active'
  ) THEN
    RAISE EXCEPTION 'edge-01 must remain active';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM central_nodes
    WHERE organization_id = '$ORGANIZATION_A'
      AND node_id = 'edge-02'
      AND state = 'revoked'
  ) THEN
    RAISE EXCEPTION 'edge-02 must be revoked';
  END IF;

  SELECT count(*) INTO credential_count
  FROM central_node_credentials
  WHERE organization_id = '$ORGANIZATION_A';
  IF credential_count <> 3 THEN
    RAISE EXCEPTION 'expected three credential generations, found %', credential_count;
  END IF;

  SELECT count(*) INTO edge_one_active_credentials
  FROM central_node_credentials c
  JOIN central_nodes n ON n.id = c.node_record_id
  WHERE n.organization_id = '$ORGANIZATION_A'
    AND n.node_id = 'edge-01'
    AND c.revoked_at IS NULL;
  IF edge_one_active_credentials <> 1 THEN
    RAISE EXCEPTION 'edge-01 must have one active credential, found %', edge_one_active_credentials;
  END IF;

  SELECT count(*) INTO edge_two_active_credentials
  FROM central_node_credentials c
  JOIN central_nodes n ON n.id = c.node_record_id
  WHERE n.organization_id = '$ORGANIZATION_A'
    AND n.node_id = 'edge-02'
    AND c.revoked_at IS NULL;
  IF edge_two_active_credentials <> 0 THEN
    RAISE EXCEPTION 'edge-02 must have no active credentials, found %', edge_two_active_credentials;
  END IF;

  IF EXISTS (
    SELECT 1
    FROM central_node_credentials
    WHERE length(secret_salt) <> 64
       OR length(secret_hash) <> 64
       OR length(secret_fingerprint) <> 16
  ) THEN
    RAISE EXCEPTION 'credential verifier metadata has an invalid shape';
  END IF;

  SELECT count(*) INTO node_audit_count
  FROM security_audit_events
  WHERE organization_id = '$ORGANIZATION_A'
    AND entity_type = 'central_node';
  IF node_audit_count <> 7 THEN
    RAISE EXCEPTION 'expected seven immutable node audit events, found %', node_audit_count;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM security_audit_events
    WHERE organization_id = '$ORGANIZATION_A'
      AND action = 'node.credential.rotated'
  ) THEN
    RAISE EXCEPTION 'credential rotation audit evidence is missing';
  END IF;

  SELECT count(*) INTO secret_leak_count
  FROM central_node_credentials
  WHERE secret_salt LIKE '%nxl_node_%'
     OR secret_hash LIKE '%nxl_node_%'
     OR secret_fingerprint LIKE '%nxl_node_%'
     OR command_sha256 LIKE '%nxl_node_%';
  IF secret_leak_count <> 0 THEN
    RAISE EXCEPTION 'plaintext provisioning secret leaked into credential persistence';
  END IF;

  IF EXISTS (
    SELECT 1 FROM security_audit_events
    WHERE entity_type = 'central_node'
      AND (
        coalesce(before_snapshot::text, '') LIKE '%nxl_node_%'
        OR coalesce(after_snapshot::text, '') LIKE '%nxl_node_%'
      )
  ) THEN
    RAISE EXCEPTION 'plaintext provisioning secret leaked into audit snapshots';
  END IF;
END
\$\$;
SQL
