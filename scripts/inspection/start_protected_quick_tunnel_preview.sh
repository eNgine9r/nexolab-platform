#!/usr/bin/env bash
# Opt-in, isolated Quick Tunnel demo. No NEXOLAB live application/DB/telemetry.
# Requires: python3, curl, cloudflared >= 2026.9.3.
# Run ONLY on a separate personal development workstation with authorized network egress.
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="${SCRIPT_DIR}/nexolab_quick_tunnel_preview.py"
PORT="${NEXOLAB_PREVIEW_PORT:-18787}"
EMAIL="${NEXOLAB_PREVIEW_ALLOWED_MAIL:-}"
FIXTURE_PID=""

cleanup() {
  if [[ -n "$FIXTURE_PID" ]]; then
    kill "$FIXTURE_PID" 2>/dev/null || true
    wait "$FIXTURE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ -z "$EMAIL" || "$EMAIL" == *","* || "$EMAIL" == *"*"* ]]; then
  echo "ERROR: NEXOLAB_PREVIEW_ALLOWED_MAIL must be one specific email address." >&2
  exit 2
fi
if [[ ! "$EMAIL" =~ ^[[:alnum:]_.+%-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}$ ]]; then
  echo "ERROR: invalid allowed email address." >&2
  exit 2
fi
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "ERROR: invalid staging fixture port." >&2
  exit 2
fi
for command in python3 curl cloudflared; do
  command -v "$command" >/dev/null || { echo "ERROR: $command is not installed." >&2; exit 3; }
done
version="$(cloudflared --version | grep -Eo '[0-9]{4}\.[0-9]+\.[0-9]+' | head -n1 || true)"
if [[ -z "$version" ]]; then
  echo "ERROR: unable to verify cloudflared version." >&2
  exit 3
fi
python3 - "$version" <<'PY'
import sys
parts = tuple(map(int, sys.argv[1].split(".")))
if parts < (2026, 9, 3):
    raise SystemExit("ERROR: cloudflared must be 2026.9.3 or newer.")
PY
echo "Starting synthetic, loopback-only NEXOLAB preview on port $PORT ..."
python3 "$FIXTURE" --port "$PORT" &
FIXTURE_PID=$!
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  kill -0 "$FIXTURE_PID" 2>/dev/null || {
    echo "ERROR: preview fixture exited; refusing to forward another service." >&2
    exit 4
  }
  if [[ "$(curl --silent --fail --max-time 1 "http://127.0.0.1:$PORT/healthz" || true)" == "preview-only" ]]; then
    break
  fi
  sleep 0.3
done
if [[ "$(curl --silent --fail --max-time 2 "http://127.0.0.1:$PORT/healthz" || true)" != "preview-only" ]]; then
  echo "ERROR: synthetic fixture identity check failed; tunnel will NOT be started." >&2
  exit 4
fi
echo "Preview fixture identity verified. Starting email-protected Quick Tunnel..."
echo "Temporary URL will appear in the cloudflared output. Ctrl+C ends access."
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" --allowed-mail "$EMAIL"
