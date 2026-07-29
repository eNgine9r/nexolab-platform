#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
FIX_REF="${NEXOLAB_FIX_REF:-origin/ops/raspberry-pi-current-head-launch}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/deployments/disabled-auth-websocket-$STAMP"
CENTRAL_ENV="$REPO/infrastructure/compose/.env.central"
FRONTEND_ENV="$REPO/.env.local"
CLIENT_PATH="src/lib/telemetry/websocket-client.ts"
TEST_PATH="src/lib/telemetry/websocket-client.test.ts"

mkdir -p "$EVIDENCE_DIR"
exec > >(tee "$EVIDENCE_DIR/deploy.log") 2>&1

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*"
}

cd "$REPO"
[[ -f "$CENTRAL_ENV" ]] || { echo "Missing $CENTRAL_ENV" >&2; exit 1; }

auth_mode="$(awk -F= '$1 == "AUTH_MODE" {print $2; exit}' "$CENTRAL_ENV")"
[[ "${auth_mode:-disabled}" == "disabled" ]] || {
  echo "Refusing disabled-auth frontend deployment because AUTH_MODE=$auth_mode" >&2
  exit 1
}

bind_ip="$(awk -F= '$1 == "CENTRAL_BIND_ADDRESS" {print $2; exit}' "$CENTRAL_ENV")"
[[ -n "$bind_ip" ]] || { echo 'CENTRAL_BIND_ADDRESS is empty' >&2; exit 1; }

for path in "$CLIENT_PATH" "$TEST_PATH"; do
  git show "HEAD:$path" > "$EVIDENCE_DIR/$(basename "$path").original"
done

restore_sources() {
  git show "HEAD:$CLIENT_PATH" > "$CLIENT_PATH"
  git show "HEAD:$TEST_PATH" > "$TEST_PATH"
}
trap restore_sources EXIT

log "Installing reviewed WebSocket fix from $FIX_REF"
git show "$FIX_REF:$CLIENT_PATH" > "$CLIENT_PATH"
git show "$FIX_REF:$TEST_PATH" > "$TEST_PATH"

log "Writing explicit live and disabled-auth frontend contract"
python3 - "$FRONTEND_ENV" "$bind_ip" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
host = sys.argv[2]
updates = {
    "NEXT_PUBLIC_NEXOLAB_DATA_MODE": "live",
    "NEXT_PUBLIC_NEXOLAB_API_BASE_URL": f"http://{host}:8082",
    "NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL": f"ws://{host}:8082/api/v1/telemetry/live",
    "NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER": "disabled",
    "NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
}

lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
positions = {}
for index, line in enumerate(lines):
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key = line.split("=", 1)[0].strip()
    positions[key] = index

for key, value in updates.items():
    rendered = f"{key}={value}"
    if key in positions:
        lines[positions[key]] = rendered
    else:
        lines.append(rendered)

path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
for key in updates:
    print(f"configured: {key}")
PY

log "Running WebSocket regression test"
npm test -- "$TEST_PATH" | tee "$EVIDENCE_DIR/websocket-test.txt"

log "Running TypeScript gate"
npm run typecheck | tee "$EVIDENCE_DIR/typecheck.txt"

log "Building production dashboard"
npm run build | tee "$EVIDENCE_DIR/frontend-build.txt"

log "Restoring main source files after successful build"
restore_sources
trap - EXIT

git diff --exit-code -- "$CLIENT_PATH" "$TEST_PATH"

log "Restarting dashboard systemd service"
sudo systemctl restart nexolab-dashboard.service

for attempt in $(seq 1 60); do
  if curl -fsS --max-time 5 http://127.0.0.1:3000 >/dev/null; then
    log "Dashboard is ready"
    break
  fi
  if [[ "$attempt" == "60" ]]; then
    sudo journalctl -u nexolab-dashboard.service --no-pager -n 150
    exit 1
  fi
  sleep 2
done

log "Verifying unauthenticated raw WebSocket transport"
node - "ws://$bind_ip:8082/api/v1/telemetry/live" <<'JS' | tee "$EVIDENCE_DIR/raw-websocket.txt"
const url = process.argv[2];
const socket = new WebSocket(url);
const timeout = setTimeout(() => {
  console.error("WebSocket message timeout");
  socket.close();
  process.exit(1);
}, 30000);

socket.addEventListener("open", () => {
  console.log(`open: ${url}`);
});

socket.addEventListener("message", (event) => {
  const payload = JSON.parse(String(event.data));
  console.log(`message: ${payload.type ?? payload.event_id ?? "telemetry"}`);
  clearTimeout(timeout);
  socket.close(1000, "verification complete");
});

socket.addEventListener("error", () => {
  clearTimeout(timeout);
  console.error("WebSocket transport error");
  process.exit(1);
});

socket.addEventListener("close", (event) => {
  if (event.code !== 1000) {
    clearTimeout(timeout);
    console.error(`unexpected close: ${event.code} ${event.reason}`);
    process.exit(1);
  }
});
JS

cat > "$EVIDENCE_DIR/manifest.txt" <<EOF
status=passed
completed_at=$(date --iso-8601=seconds)
source_commit=$(git rev-parse HEAD)
fix_ref=$FIX_REF
frontend_auth_provider=disabled
dashboard=http://$bind_ip:3000
websocket=ws://$bind_ip:8082/api/v1/telemetry/live
evidence=$EVIDENCE_DIR
EOF

log "DISABLED-AUTH WEBSOCKET DEPLOYMENT PASSED"
echo "Dashboard: http://$bind_ip:3000"
echo "Evidence:  $EVIDENCE_DIR"
