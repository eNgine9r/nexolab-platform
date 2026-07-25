#!/usr/bin/env bash
set -Eeuo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$COMPOSE_DIR/../.." && pwd)"
ENV_FILE="${2:-$COMPOSE_DIR/.env.central}"
ACTION="${1:-apply}"

required_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Required command is missing: %s\n' "$1" >&2
    exit 1
  fi
}

load_environment() {
  if [[ ! -f "$ENV_FILE" ]]; then
    printf 'Central environment file not found: %s\n' "$ENV_FILE" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a

  : "${CENTRAL_BIND_ADDRESS:?CENTRAL_BIND_ADDRESS is required}"
  : "${CENTRAL_DASHBOARD_PORT:?CENTRAL_DASHBOARD_PORT is required}"
  : "${CENTRAL_API_PORT:?CENTRAL_API_PORT is required}"
  : "${CENTRAL_OBJECT_STORAGE_PORT:?CENTRAL_OBJECT_STORAGE_PORT is required}"
  : "${TAILSCALE_NODE_FQDN:?TAILSCALE_NODE_FQDN is required}"
  : "${TAILSCALE_DASHBOARD_HTTPS_PORT:?TAILSCALE_DASHBOARD_HTTPS_PORT is required}"
  : "${TAILSCALE_API_HTTPS_PORT:?TAILSCALE_API_HTTPS_PORT is required}"
  : "${TAILSCALE_STORAGE_HTTPS_PORT:?TAILSCALE_STORAGE_HTTPS_PORT is required}"
  : "${NEXT_PUBLIC_NEXOLAB_API_BASE_URL:?NEXT_PUBLIC_NEXOLAB_API_BASE_URL is required}"
  : "${NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL:?NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL is required}"
  : "${OBJECT_STORAGE_PUBLIC_ENDPOINT_URL:?OBJECT_STORAGE_PUBLIC_ENDPOINT_URL is required}"
  : "${CORS_ALLOWED_ORIGINS:?CORS_ALLOWED_ORIGINS is required}"
  : "${OPERATOR_IDENTITY_MODE:?OPERATOR_IDENTITY_MODE is required}"

  TAILSCALE_NODE_FQDN="${TAILSCALE_NODE_FQDN%.}"
  export TAILSCALE_NODE_FQDN
}

validate_boundary() {
  if [[ "$CENTRAL_BIND_ADDRESS" != "127.0.0.1" ]]; then
    printf 'Tailscale Serve profile requires CENTRAL_BIND_ADDRESS=127.0.0.1.\n' >&2
    exit 1
  fi
  if [[ "$TAILSCALE_NODE_FQDN" != *.ts.net ]]; then
    printf 'TAILSCALE_NODE_FQDN must be a MagicDNS *.ts.net name.\n' >&2
    exit 1
  fi
  if [[ "$OPERATOR_IDENTITY_MODE" != "tailscale_serve" ]]; then
    printf 'OPERATOR_IDENTITY_MODE must be tailscale_serve for trusted proxy identity.\n' >&2
    exit 1
  fi

  local dashboard_origin="https://$TAILSCALE_NODE_FQDN"
  if [[ "$TAILSCALE_DASHBOARD_HTTPS_PORT" != "443" ]]; then
    dashboard_origin="$dashboard_origin:$TAILSCALE_DASHBOARD_HTTPS_PORT"
  fi
  local api_origin="https://$TAILSCALE_NODE_FQDN:$TAILSCALE_API_HTTPS_PORT"
  local storage_origin="https://$TAILSCALE_NODE_FQDN:$TAILSCALE_STORAGE_HTTPS_PORT"

  if [[ "$CORS_ALLOWED_ORIGINS" != "$dashboard_origin" ]]; then
    printf 'CORS_ALLOWED_ORIGINS must exactly equal %s.\n' "$dashboard_origin" >&2
    exit 1
  fi
  if [[ "$NEXT_PUBLIC_NEXOLAB_API_BASE_URL" != "$api_origin" ]]; then
    printf 'NEXT_PUBLIC_NEXOLAB_API_BASE_URL must equal %s.\n' "$api_origin" >&2
    exit 1
  fi
  if [[ "$NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL" != "wss://$TAILSCALE_NODE_FQDN:$TAILSCALE_API_HTTPS_PORT/api/v1/telemetry/live" ]]; then
    printf 'NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL does not match the controlled WSS origin.\n' >&2
    exit 1
  fi
  if [[ "$OBJECT_STORAGE_PUBLIC_ENDPOINT_URL" != "$storage_origin" ]]; then
    printf 'OBJECT_STORAGE_PUBLIC_ENDPOINT_URL must equal %s.\n' "$storage_origin" >&2
    exit 1
  fi

  local actual_fqdn
  actual_fqdn="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
  if [[ "$actual_fqdn" != "$TAILSCALE_NODE_FQDN" ]]; then
    printf 'Configured Tailscale FQDN %s does not match this node %s.\n' "$TAILSCALE_NODE_FQDN" "$actual_fqdn" >&2
    exit 1
  fi
}

compose() {
  docker compose \
    --env-file "$ENV_FILE" \
    --file "$COMPOSE_DIR/compose.central.yaml" \
    --file "$COMPOSE_DIR/compose.central-dashboard.yaml" \
    "$@"
}

apply_serve() {
  compose config --quiet
  compose up -d --build --wait

  tailscale serve reset
  tailscale serve --yes --bg --https="$TAILSCALE_DASHBOARD_HTTPS_PORT" \
    "http://127.0.0.1:$CENTRAL_DASHBOARD_PORT"
  tailscale serve --yes --bg --https="$TAILSCALE_API_HTTPS_PORT" \
    "http://127.0.0.1:$CENTRAL_API_PORT"
  tailscale serve --yes --bg --https="$TAILSCALE_STORAGE_HTTPS_PORT" \
    "http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT"

  curl --fail --silent --show-error "http://127.0.0.1:$CENTRAL_DASHBOARD_PORT" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:$CENTRAL_API_PORT/health/ready" >/dev/null
  curl --fail --silent --show-error "http://127.0.0.1:$CENTRAL_OBJECT_STORAGE_PORT/minio/health/live" >/dev/null

  printf '\nTailscale Serve configuration applied.\n'
  tailscale serve status
}

show_status() {
  compose ps --all
  tailscale serve status
}

reset_serve() {
  tailscale serve reset
  printf 'Tailscale Serve routes removed. Central containers and persistent volumes were not deleted.\n'
}

for command in tailscale docker curl python3; do
  required_command "$command"
done
load_environment
validate_boundary

case "$ACTION" in
  apply)
    apply_serve
    ;;
  status)
    show_status
    ;;
  reset)
    reset_serve
    ;;
  *)
    printf 'Usage: %s [apply|status|reset] [env-file]\n' "$0" >&2
    exit 2
    ;;
esac
