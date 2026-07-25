#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/infrastructure/compose/.env.remote-acceptance}"
RUN_SUFFIX="$(date -u +%Y%m%dT%H%M%SZ)-$$"

required_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "$1" >&2
    exit 1
  fi
}

if [[ ! -f "$ENV_FILE" ]]; then
  printf 'Remote acceptance environment file not found: %s\n' "$ENV_FILE" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${NEXOLAB_REMOTE_DASHBOARD_URL:?NEXOLAB_REMOTE_DASHBOARD_URL is required}"
: "${NEXOLAB_REMOTE_API_URL:?NEXOLAB_REMOTE_API_URL is required}"
: "${NEXOLAB_REMOTE_STORAGE_ORIGIN:?NEXOLAB_REMOTE_STORAGE_ORIGIN is required}"
: "${NEXOLAB_REMOTE_WEBSOCKET_URL:?NEXOLAB_REMOTE_WEBSOCKET_URL is required}"
: "${NEXOLAB_EXPECTED_OPERATOR_LOGIN:?NEXOLAB_EXPECTED_OPERATOR_LOGIN is required}"

export NEXOLAB_REMOTE_EQUIPMENT_ID="${NEXOLAB_REMOTE_EQUIPMENT_ID:-acceptance-$RUN_SUFFIX}"
export NEXOLAB_REMOTE_EVIDENCE_DIR="${NEXOLAB_REMOTE_EVIDENCE_DIR:-$ROOT_DIR/runtime/evidence/refrigeration-remote-acceptance-$RUN_SUFFIX}"
export NEXT_TELEMETRY_DISABLED=1
mkdir -p "$NEXOLAB_REMOTE_EVIDENCE_DIR"

for command in curl openssl npm python3; do
  required_command "$command"
done

url_origin() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
port = f":{url.port}" if url.port else ""
print(f"{url.scheme}://{url.hostname}{port}")
PY
}

url_host() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit
print(urlsplit(sys.argv[1]).hostname or "")
PY
}

url_port() {
  python3 - "$1" <<'PY'
import sys
from urllib.parse import urlsplit
url = urlsplit(sys.argv[1])
print(url.port or (443 if url.scheme in {"https", "wss"} else 80))
PY
}

for url in "$NEXOLAB_REMOTE_DASHBOARD_URL" "$NEXOLAB_REMOTE_API_URL" "$NEXOLAB_REMOTE_STORAGE_ORIGIN"; do
  if [[ "$url" != https://* ]]; then
    printf 'Remote acceptance URL must use HTTPS: %s\n' "$url" >&2
    exit 1
  fi
done
if [[ "$NEXOLAB_REMOTE_WEBSOCKET_URL" != wss://* ]]; then
  printf 'NEXOLAB_REMOTE_WEBSOCKET_URL must use WSS.\n' >&2
  exit 1
fi

DASHBOARD_ORIGIN="$(url_origin "$NEXOLAB_REMOTE_DASHBOARD_URL")"
API_ORIGIN="$(url_origin "$NEXOLAB_REMOTE_API_URL")"
STORAGE_ORIGIN="$(url_origin "$NEXOLAB_REMOTE_STORAGE_ORIGIN")"
if [[ "$DASHBOARD_ORIGIN" == "$API_ORIGIN" ]]; then
  printf 'Dashboard and API must use separate origins so exact CORS is exercised.\n' >&2
  exit 1
fi
if [[ "$STORAGE_ORIGIN" != "${NEXOLAB_REMOTE_STORAGE_ORIGIN%/}" ]]; then
  printf 'NEXOLAB_REMOTE_STORAGE_ORIGIN must not contain a path.\n' >&2
  exit 1
fi

collect_tls() {
  local label="$1"
  local url="$2"
  local host port
  host="$(url_host "$url")"
  port="$(url_port "$url")"
  {
    printf 'endpoint=%s\n' "$url"
    printf 'host=%s\nport=%s\n' "$host" "$port"
    openssl s_client \
      -connect "$host:$port" \
      -servername "$host" \
      -verify_return_error \
      -brief </dev/null
    openssl s_client -connect "$host:$port" -servername "$host" -showcerts </dev/null 2>/dev/null \
      | openssl x509 -noout -subject -issuer -serial -dates -ext subjectAltName -fingerprint -sha256
  } >"$NEXOLAB_REMOTE_EVIDENCE_DIR/tls-$label.txt" 2>&1
}

collect_tls dashboard "$NEXOLAB_REMOTE_DASHBOARD_URL"
collect_tls api "$NEXOLAB_REMOTE_API_URL"
collect_tls storage "$NEXOLAB_REMOTE_STORAGE_ORIGIN"

curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
  "$NEXOLAB_REMOTE_DASHBOARD_URL" >"$NEXOLAB_REMOTE_EVIDENCE_DIR/dashboard.html"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
  "$NEXOLAB_REMOTE_API_URL/health/ready" >"$NEXOLAB_REMOTE_EVIDENCE_DIR/api-readiness.json"
curl --fail --silent --show-error --proto '=https' --tlsv1.2 \
  "$NEXOLAB_REMOTE_STORAGE_ORIGIN/minio/health/live" >"$NEXOLAB_REMOTE_EVIDENCE_DIR/storage-readiness.txt"

ALLOWED_HEADERS="$NEXOLAB_REMOTE_EVIDENCE_DIR/cors-allowed.txt"
DENIED_HEADERS="$NEXOLAB_REMOTE_EVIDENCE_DIR/cors-denied.txt"
DRAFT_HEADERS="$NEXOLAB_REMOTE_EVIDENCE_DIR/draft-headers.txt"

curl --silent --show-error --dump-header "$ALLOWED_HEADERS" --output /dev/null \
  --request OPTIONS \
  --header "Origin: $DASHBOARD_ORIGIN" \
  --header 'Access-Control-Request-Method: GET' \
  "$NEXOLAB_REMOTE_API_URL/api/v1/operator/session"

grep -Eqi "^access-control-allow-origin: ${DASHBOARD_ORIGIN//./\.}\r?$" "$ALLOWED_HEADERS"

curl --silent --show-error --dump-header "$DENIED_HEADERS" --output /dev/null \
  --request OPTIONS \
  --header 'Origin: https://untrusted.invalid' \
  --header 'Access-Control-Request-Method: GET' \
  "$NEXOLAB_REMOTE_API_URL/api/v1/operator/session"
if grep -Eqi '^access-control-allow-origin:' "$DENIED_HEADERS"; then
  printf 'Untrusted browser origin received an Access-Control-Allow-Origin header.\n' >&2
  exit 1
fi

curl --fail --silent --show-error --dump-header "$DRAFT_HEADERS" --output /dev/null \
  --header "Origin: $DASHBOARD_ORIGIN" \
  "$NEXOLAB_REMOTE_API_URL/api/v1/equipment/$NEXOLAB_REMOTE_EQUIPMENT_ID/layout/draft"
grep -Eqi '^access-control-expose-headers:.*etag' "$DRAFT_HEADERS"
grep -Eqi '^etag: W/"layout-draft-v1"' "$DRAFT_HEADERS"

SESSION_FILE="$NEXOLAB_REMOTE_EVIDENCE_DIR/operator-session-preflight.json"
curl --fail --silent --show-error \
  --header 'X-Actor-Id: spoofed-remote-actor' \
  "$NEXOLAB_REMOTE_API_URL/api/v1/operator/session" >"$SESSION_FILE"
python3 - "$SESSION_FILE" "$NEXOLAB_EXPECTED_OPERATOR_LOGIN" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
expected = sys.argv[2]
assert payload["actor_id"] == expected, payload
assert payload["provider"] == "tailscale", payload
assert payload["authenticated"] is True, payload
PY

if command -v tailscale >/dev/null 2>&1; then
  tailscale status >"$NEXOLAB_REMOTE_EVIDENCE_DIR/tailscale-status.txt" 2>&1 || true
fi

cd "$ROOT_DIR"
npm install --no-audit --no-fund
if [[ "${PLAYWRIGHT_INSTALL_WITH_DEPS:-0}" == "1" ]]; then
  npx playwright install --with-deps chromium
else
  npx playwright install chromium
fi
npx playwright test --config=playwright.remote.config.ts

printf '\nRemote acceptance evidence: %s\n' "$NEXOLAB_REMOTE_EVIDENCE_DIR"
printf 'Remote equipment id: %s\n' "$NEXOLAB_REMOTE_EQUIPMENT_ID"
