#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="nexolab-device-agent-fleet-tls-acceptance"
PRIVATE_ROOT="${TMPDIR:-/tmp}/${PROJECT_NAME}-private"
EVIDENCE_DIR="$ROOT_DIR/test-results-device-agent-fleet-tls"

export FLEET_PROJECT_NAME="$PROJECT_NAME"
export FLEET_EVIDENCE_DIR="$EVIDENCE_DIR"
export FLEET_EXTRA_COMPOSE_FILE="$ROOT_DIR/infrastructure/compose/compose.mqtt-tls-fleet-acceptance.yaml"
export FLEET_SETUP_HOOK="$ROOT_DIR/scripts/generate-mqtt-tls-acceptance-material.sh"
export FLEET_FRONTEND_PORT="${FLEET_FRONTEND_PORT:-3114}"
export FLEET_API_PORT="${FLEET_API_PORT:-8094}"
export FLEET_MQTT_PORT="${FLEET_MQTT_PORT:-1894}"
export FLEET_MQTT_TLS_PORT="${FLEET_MQTT_TLS_PORT:-8894}"
export MQTT_TLS_SERVER_DIR="$PRIVATE_ROOT/mqtt-server-tls"
export BROKER_CONTROL_TLS_EVIDENCE_DIR="$EVIDENCE_DIR"

exec bash "$ROOT_DIR/scripts/run-device-agent-fleet-acceptance.sh"
