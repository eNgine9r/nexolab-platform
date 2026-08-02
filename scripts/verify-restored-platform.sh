#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: verify-restored-platform.sh <project-name> <compose-file> <evidence-dir>" >&2
  exit 64
fi

PROJECT_NAME=$1
COMPOSE_FILE=$2
EVIDENCE_DIR=$3
API_PORT="${DR_RESTORE_API_PORT:-8094}"
API_BASE_URL="http://127.0.0.1:${API_PORT}"
ORGANIZATION_ID="00000000-0000-0000-0000-000000000099"
EDGE_01_USERNAME="node:${ORGANIZATION_ID}:edge-01"
EDGE_01_CLIENT_ID="nexolab-${ORGANIZATION_ID}-edge-01"
POST_RESTORE_EVENT_ID="30000000-0000-0000-0000-000000000001"
STARTED_AT="$(date +%s)"
TOKEN_FILE="${DR_WORK_DIR:?DR_WORK_DIR is required}/source-local-auth-tokens.json"
LOCAL_AUTH_PASSWORD_FILE="${DR_SECRETS_DIR:?DR_SECRETS_DIR is required}/local-auth-password"

compose() {
  docker compose --project-name "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

capture_failure() {
  local status=$?
  set +e
  compose ps --all >"$EVIDENCE_DIR/application-compose-ps.txt" 2>&1 || true
  compose logs --no-color restore-telemetry-service restore-postgres restore-mqtt restore-minio \
    >"$EVIDENCE_DIR/application-services.log" 2>&1 || true
  exit "$status"
}
trap capture_failure ERR

compose up -d --wait restore-telemetry-service

python3 - "$API_BASE_URL" "$EVIDENCE_DIR" "$TOKEN_FILE" "$ORGANIZATION_ID" <<'PY'
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import sys

base_url = sys.argv[1]
evidence = Path(sys.argv[2])
tokens = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
organization_id = sys.argv[4]
access_token = tokens["access_token"]
expected = {
    "20000000-0000-0000-0000-000000000001",
    "20000000-0000-0000-0000-000000000002",
}

def authorized_json(path: str) -> dict[str, object]:
    request = Request(
        f"{base_url}{path}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Organization-ID": organization_id,
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=10) as response:
        return json.load(response)

with urlopen(f"{base_url}/health/ready", timeout=10) as response:
    ready = json.load(response)
evidence.joinpath("restored-ready.json").write_text(
    json.dumps(ready, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
latest = authorized_json("/api/v1/telemetry/latest?limit=20")
evidence.joinpath("restored-latest.json").write_text(
    json.dumps(latest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
history_query = urlencode(
    {"from": "2026-07-28T00:00:00+00:00", "to": "2026-07-29T00:00:00+00:00", "limit": 20}
)
history = authorized_json(f"/api/v1/telemetry/history?{history_query}")
evidence.joinpath("restored-history.json").write_text(
    json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
for label, payload in (("latest", latest), ("history", history)):
    found = {item["event_id"] for item in payload["items"]}
    if not expected.issubset(found):
        raise SystemExit(f"Restored telemetry is missing from {label}: {expected - found}")
PY

compose exec -T restore-telemetry-service python - \
  "$ORGANIZATION_ID" <"$TOKEN_FILE" <<'PY'
from __future__ import annotations

import asyncio
import json
import sys
import websockets

organization_id = sys.argv[1]
tokens = json.load(sys.stdin)

async def main() -> None:
    uri = "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01"
    async with websockets.connect(uri, open_timeout=5, close_timeout=5) as socket:
        await socket.send(json.dumps({
            "type": "authenticate",
            "access_token": tokens["access_token"],
            "organization_id": organization_id,
        }))
        response = json.loads(await asyncio.wait_for(socket.recv(), timeout=5))
        if response.get("type") != "authenticated":
            raise SystemExit(f"Restored WebSocket authentication failed: {response}")

asyncio.run(main())
PY

compose exec -T restore-telemetry-service python - \
  "$ORGANIZATION_ID" "$EDGE_01_USERNAME" "$EDGE_01_CLIENT_ID" \
  "$POST_RESTORE_EVENT_ID" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import json
import sys
import threading

import paho.mqtt.client as mqtt

organization_id, username, client_id, event_id = sys.argv[1:]
password = Path("/run/secrets/nexolab/edge-01-password").read_text(
    encoding="utf-8"
).strip()
connected = threading.Event()
errors: list[str] = []

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
client.username_pw_set(username, password)
del password


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        connected.set()
        return
    errors.append(str(reason_code))
    connected.set()


client.on_connect = on_connect
client.connect("restore-mqtt", 1883, keepalive=30)
client.loop_start()
if not connected.wait(10) or errors:
    raise SystemExit(f"Restored node identity could not connect: {errors}")

payload = {
    "event_id": event_id,
    "node_id": "edge-01",
    "captured_at": datetime.now(UTC).isoformat(),
    "metric": "temperature.air",
    "value": 5.25,
    "unit": "degC",
    "quality": "valid",
    "source": "disaster-recovery-acceptance",
    "equipment_id": "SIM-DR-POST-RESTORE",
    "channel_id": "ambient-temperature",
    "alarm": None,
    "raw_value": 525,
    "raw_status": 0,
    "node_sequence": 2,
}
body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
topic = f"nexolab/v1/{organization_id}/edge-01/telemetry"
for _ in range(2):
    result = client.publish(topic, body, qos=1)
    result.wait_for_publish(timeout=10)
    if result.rc != mqtt.MQTT_ERR_SUCCESS or not result.is_published():
        raise SystemExit("Post-restore QoS 1 publish was not acknowledged")
client.disconnect()
client.loop_stop()
PY

POST_RESTORE_ROW_COUNT=0
for _ in $(seq 1 80); do
  POST_RESTORE_ROW_COUNT="$(compose exec -T restore-postgres \
    psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
    "SELECT COUNT(*) FROM telemetry_samples WHERE event_id = '$POST_RESTORE_EVENT_ID'")"
  if [[ "$POST_RESTORE_ROW_COUNT" = "1" ]]; then
    break
  fi
  sleep 0.25
done
test "$POST_RESTORE_ROW_COUNT" = "1"

TOTAL_TELEMETRY_ROWS="$(compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
  "SELECT COUNT(*) FROM telemetry_samples")"
DEAD_LETTER_ROWS="$(compose exec -T restore-postgres \
  psql -U "$DR_POSTGRES_USER" -d "$DR_POSTGRES_DB" -Atc \
  "SELECT COUNT(*) FROM telemetry_dead_letters")"
test "$TOTAL_TELEMETRY_ROWS" = "3"
test "$DEAD_LETTER_ROWS" = "0"

python3 - "$API_BASE_URL" "$EVIDENCE_DIR" "$POST_RESTORE_EVENT_ID" \
  "$TOKEN_FILE" "$ORGANIZATION_ID" <<'PY'
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import sys

base_url = sys.argv[1]
evidence = Path(sys.argv[2])
event_id = sys.argv[3]
tokens = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
organization_id = sys.argv[5]
query = urlencode({"node_id": "edge-01", "equipment_id": "SIM-DR-POST-RESTORE", "limit": 5})
request = Request(
    f"{base_url}/api/v1/telemetry/latest?{query}",
    headers={
        "Authorization": f"Bearer {tokens['access_token']}",
        "X-Organization-ID": organization_id,
        "Accept": "application/json",
    },
)
with urlopen(request, timeout=10) as response:
    payload = json.load(response)
if payload["count"] != 1 or payload["items"][0]["event_id"] != event_id:
    raise SystemExit("Post-restore telemetry is not visible exactly once through REST")
evidence.joinpath("post-restore-latest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
PY

python3 - "$API_BASE_URL" "$TOKEN_FILE" "$LOCAL_AUTH_PASSWORD_FILE" \
  "$ORGANIZATION_ID" "$EVIDENCE_DIR" <<'PY'
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import sys

base_url, token_path, password_path, organization_id, evidence_dir = sys.argv[1:]
tokens = json.loads(Path(token_path).read_text(encoding="utf-8"))
password = Path(password_path).read_text(encoding="utf-8").strip()

def call(path: str, *, token: str | None = None, payload: dict[str, str] | None = None) -> tuple[int, object | None]:
    headers = {"Accept": "application/json"}
    data = None
    method = "GET"
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Organization-ID"] = organization_id
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        method = "POST"
    request = Request(f"{base_url}{path}", headers=headers, data=data, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read()
            return response.status, json.loads(body) if body else None
    except HTTPError as error:
        body = error.read()
        return error.code, json.loads(body) if body else None

original_status, original_session = call(
    "/api/v1/auth/session", token=tokens["access_token"]
)
if original_status != 200:
    raise SystemExit(f"pre-backup local access session was not restored: {original_status}")
refresh_status, refreshed = call(
    "/api/v1/auth/local/refresh", payload={"refresh_token": tokens["refresh_token"]}
)
if refresh_status != 200 or not isinstance(refreshed, dict):
    raise SystemExit(f"pre-backup refresh session was not restored: {refresh_status}")
refreshed_status, _ = call(
    "/api/v1/auth/session", token=refreshed["access_token"]
)
if refreshed_status != 200:
    raise SystemExit("refreshed access token is invalid after restore")
logout_status, _ = call(
    "/api/v1/auth/local/logout", payload={"refresh_token": refreshed["refresh_token"]}
)
if logout_status != 204:
    raise SystemExit(f"restored session logout failed: {logout_status}")
revoked_original_status, _ = call(
    "/api/v1/auth/session", token=tokens["access_token"]
)
revoked_refreshed_status, _ = call(
    "/api/v1/auth/session", token=refreshed["access_token"]
)
if (revoked_original_status, revoked_refreshed_status) != (401, 401):
    raise SystemExit("restored session revocation did not invalidate both access tokens")
login_status, new_login = call(
    "/api/v1/auth/local/login",
    payload={"username": "recovery-administrator", "password": password},
)
if login_status != 200 or not isinstance(new_login, dict):
    raise SystemExit(f"new local login failed after restore: {login_status}")
new_session_status, new_session = call(
    "/api/v1/auth/session", token=new_login["access_token"]
)
if new_session_status != 200:
    raise SystemExit("new local session is invalid after restore")
call(
    "/api/v1/auth/local/logout", payload={"refresh_token": new_login["refresh_token"]}
)
identity = original_session.get("identity", {}) if isinstance(original_session, dict) else {}
Path(evidence_dir, "local-auth-recovery.json").write_text(
    json.dumps(
        {
            "provider": identity.get("provider"),
            "subject": identity.get("subject"),
            "pre_backup_access_session_restored": True,
            "pre_backup_refresh_session_restored": True,
            "refresh_rotation_after_restore": True,
            "logout_revoked_original_access": revoked_original_status == 401,
            "logout_revoked_refreshed_access": revoked_refreshed_status == 401,
            "new_password_login_after_restore": True,
        },
        indent=2,
        sort_keys=True,
    ) + "\n",
    encoding="utf-8",
)
PY

APPLICATION_SECONDS="$(( $(date +%s) - STARTED_AT ))"
python3 - "$EVIDENCE_DIR/application-summary.json" <<PY
from pathlib import Path
import json
import sys

payload = {
    "schema_version": 1,
    "ready": True,
    "restored_rest_rows": 2,
    "websocket_handshake": True,
    "restored_node_identity_connected": True,
    "post_restore_event_id": "$POST_RESTORE_EVENT_ID",
    "post_restore_duplicate_publishes": 2,
    "post_restore_exactly_once_rows": int("$POST_RESTORE_ROW_COUNT"),
    "total_telemetry_rows": int("$TOTAL_TELEMETRY_ROWS"),
    "dead_letter_rows": int("$DEAD_LETTER_ROWS"),
    "local_auth": {
        "pre_backup_access_session_restored": True,
        "pre_backup_refresh_session_restored": True,
        "refresh_rotation_after_restore": True,
        "logout_revocation": True,
        "new_password_login_after_restore": True,
        "websocket_authenticated": True,
    },
    "application_verification_seconds": $APPLICATION_SECONDS,
}
Path(sys.argv[1]).write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY

trap - ERR
echo "Restored NEXOLAB application flows passed."
