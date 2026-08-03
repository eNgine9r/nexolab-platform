#!/usr/bin/env bash

nexolab_validate_runtime_mode() {
  local mode=${1:-}
  case "$mode" in
    lan|standalone)
      return 0
      ;;
    *)
      printf 'ERROR: unsupported runtime mode: %s (expected lan or standalone)\n' "${mode:-<empty>}" >&2
      return 64
      ;;
  esac
}

nexolab_configure_runtime_contract() {
  local mode=${1:-}
  local lan_bind_address=${2:-}

  nexolab_validate_runtime_mode "$mode" || return $?

  NEXOLAB_RUNTIME_MODE="$mode"
  if [[ "$mode" == "standalone" ]]; then
    NEXOLAB_HOST_BIND_ADDRESS="127.0.0.1"
    NEXOLAB_DASHBOARD_BIND_ADDRESS="127.0.0.1"
    NEXOLAB_DASHBOARD_ORIGIN="http://127.0.0.1:3000"
    NEXOLAB_API_BASE_URL="http://127.0.0.1:8082"
    NEXOLAB_WEBSOCKET_URL="ws://127.0.0.1:8082/api/v1/telemetry/live"
    NEXOLAB_OBJECT_STORAGE_PUBLIC_URL="http://127.0.0.1:9000"
    NEXOLAB_CORS_ALLOWED_ORIGINS="http://127.0.0.1:3000,http://localhost:3000"
    NEXOLAB_EDGE_CENTRAL_MQTT_HOST="central-mqtt"
    NEXOLAB_EDGE_CENTRAL_MQTT_PORT="1883"
    NEXOLAB_EDGE_CENTRAL_API_BASE_URL="http://telemetry-service:8082"
    NEXOLAB_EDGE_CENTRAL_WEBSOCKET_URL="ws://telemetry-service:8082/api/v1/telemetry/live"
    NEXOLAB_USE_STANDALONE_OVERLAYS="true"
    NEXOLAB_SYSTEMD_AFTER="docker.service"
    NEXOLAB_SYSTEMD_WANTS=""
    return 0
  fi

  if [[ -z "$lan_bind_address" || "$lan_bind_address" == "127.0.0.1" ]]; then
    printf 'ERROR: lan runtime mode requires an assigned non-loopback IPv4 address\n' >&2
    return 64
  fi

  NEXOLAB_HOST_BIND_ADDRESS="$lan_bind_address"
  NEXOLAB_DASHBOARD_BIND_ADDRESS="0.0.0.0"
  NEXOLAB_DASHBOARD_ORIGIN="http://${lan_bind_address}:3000"
  NEXOLAB_API_BASE_URL="http://${lan_bind_address}:8082"
  NEXOLAB_WEBSOCKET_URL="ws://${lan_bind_address}:8082/api/v1/telemetry/live"
  NEXOLAB_OBJECT_STORAGE_PUBLIC_URL="http://${lan_bind_address}:9000"
  NEXOLAB_CORS_ALLOWED_ORIGINS="http://127.0.0.1:3000,http://localhost:3000,http://${lan_bind_address}:3000"
  NEXOLAB_EDGE_CENTRAL_MQTT_HOST="$lan_bind_address"
  NEXOLAB_EDGE_CENTRAL_MQTT_PORT="1884"
  NEXOLAB_EDGE_CENTRAL_API_BASE_URL="http://${lan_bind_address}:8082"
  NEXOLAB_EDGE_CENTRAL_WEBSOCKET_URL="ws://${lan_bind_address}:8082/api/v1/telemetry/live"
  NEXOLAB_USE_STANDALONE_OVERLAYS="false"
  NEXOLAB_SYSTEMD_AFTER="network-online.target docker.service"
  NEXOLAB_SYSTEMD_WANTS="network-online.target"
}
