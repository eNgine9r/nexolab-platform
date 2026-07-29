#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

REPO="${NEXOLAB_REPO:-$HOME/nexolab-platform}"
EDGE_ENV="${EDGE_ENV:-$REPO/infrastructure/compose/.env.edge-central}"
EDGE_COMPOSE="$REPO/infrastructure/compose/compose.edge.yaml"
HARDWARE_COMPOSE="$REPO/infrastructure/compose/compose.hardware.yaml"
BRIDGE_COMPOSE="$REPO/infrastructure/compose/compose.edge-central-bridge.yaml"
DEVICE_AGENT_IMAGE="${DEVICE_AGENT_IMAGE:-nexolab-device-agent:local}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
EVIDENCE_DIR="$REPO/runtime/deployments/edge-volume-ownership-$STAMP"
CONTAINER_NAME="nexolab-edge-device-agent-1"

mkdir -p "$EVIDENCE_DIR"
cd "$REPO"

for command in docker curl; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "ERROR: missing command: $command" >&2
    exit 127
  }
done

docker compose version >/dev/null
[[ -f "$EDGE_ENV" ]] || {
  echo "ERROR: edge environment file is missing: $EDGE_ENV" >&2
  exit 66
}

TARGET_UID="$(docker run --rm --entrypoint /usr/bin/python3 "$DEVICE_AGENT_IMAGE" -c 'import os; print(os.getuid())')"
TARGET_GID="$(docker run --rm --entrypoint /usr/bin/python3 "$DEVICE_AGENT_IMAGE" -c 'import os; print(os.getgid())')"
[[ "$TARGET_UID" =~ ^[0-9]+$ && "$TARGET_GID" =~ ^[0-9]+$ ]] || {
  echo "ERROR: could not resolve runtime uid/gid for $DEVICE_AGENT_IMAGE" >&2
  exit 65
}

EDGE_VOLUME="$(docker inspect "$CONTAINER_NAME" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/nexolab"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"
if [[ -z "$EDGE_VOLUME" ]]; then
  EDGE_VOLUME="nexolab-edge_edge-data"
fi

docker volume inspect "$EDGE_VOLUME" > "$EVIDENCE_DIR/volume-inspect-before.json"

echo "Device Agent image: $DEVICE_AGENT_IMAGE"
echo "Runtime uid:gid: $TARGET_UID:$TARGET_GID"
echo "Edge data volume: $EDGE_VOLUME"
echo "Evidence: $EVIDENCE_DIR"

docker compose \
  --env-file "$EDGE_ENV" \
  -f "$EDGE_COMPOSE" \
  -f "$HARDWARE_COMPOSE" \
  -f "$BRIDGE_COMPOSE" \
  stop device-agent

docker run --rm \
  -v "$EDGE_VOLUME:/data:ro" \
  -v "$EVIDENCE_DIR:/backup" \
  python:3.13-alpine \
  sh -ec 'ls -lan /data > /backup/ownership-before.txt; tar -C /data -czf /backup/edge-data-before-ownership-migration.tar.gz .'

[[ -s "$EVIDENCE_DIR/edge-data-before-ownership-migration.tar.gz" ]] || {
  echo "ERROR: edge volume backup is empty" >&2
  exit 1
}

docker run --rm \
  -e TARGET_UID="$TARGET_UID" \
  -e TARGET_GID="$TARGET_GID" \
  -v "$EDGE_VOLUME:/data" \
  python:3.13-alpine \
  sh -ec '
    chown -R "$TARGET_UID:$TARGET_GID" /data
    find /data -type d -exec chmod u+rwx {} +
    find /data -type f -exec chmod u+rw {} +
  '

docker run --rm \
  -v "$EDGE_VOLUME:/data:ro" \
  -v "$EVIDENCE_DIR:/backup" \
  python:3.13-alpine \
  sh -ec 'ls -lan /data > /backup/ownership-after.txt'

docker compose \
  --env-file "$EDGE_ENV" \
  -f "$EDGE_COMPOSE" \
  -f "$HARDWARE_COMPOSE" \
  -f "$BRIDGE_COMPOSE" \
  up -d --force-recreate device-agent

for _ in $(seq 1 60); do
  if curl -fsS --max-time 5 http://127.0.0.1:8081/health > "$EVIDENCE_DIR/device-agent-health.json"; then
    echo "OK: Device Agent is healthy"
    cat "$EVIDENCE_DIR/device-agent-health.json"
    echo
    docker compose \
      --env-file "$EDGE_ENV" \
      -f "$EDGE_COMPOSE" \
      -f "$HARDWARE_COMPOSE" \
      -f "$BRIDGE_COMPOSE" \
      ps -a | tee "$EVIDENCE_DIR/edge-ps.txt"
    exit 0
  fi
  sleep 2
done

docker compose \
  --env-file "$EDGE_ENV" \
  -f "$EDGE_COMPOSE" \
  -f "$HARDWARE_COMPOSE" \
  -f "$BRIDGE_COMPOSE" \
  logs --tail=250 --no-color device-agent > "$EVIDENCE_DIR/device-agent-failure.log" 2>&1 || true

echo "ERROR: Device Agent did not become healthy; see $EVIDENCE_DIR/device-agent-failure.log" >&2
exit 1
