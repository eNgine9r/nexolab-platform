#!/bin/sh
set -eu

DYNSEC_CONFIG="${NEXOLAB_MQTT_DYNSEC_CONFIG:-/mosquitto/data/dynamic-security.json}"
ADMIN_USERNAME="${NEXOLAB_MQTT_ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD_FILE="${NEXOLAB_MQTT_ADMIN_PASSWORD_FILE:-/run/secrets/mqtt_admin_password}"

initialize_dynamic_security() {
  if [ -s "$DYNSEC_CONFIG" ]; then
    return
  fi

  if [ ! -r "$ADMIN_PASSWORD_FILE" ]; then
    echo "Dynamic Security admin password secret is required for first start." >&2
    exit 64
  fi

  admin_password="$(cat "$ADMIN_PASSWORD_FILE")"
  if [ -z "$admin_password" ]; then
    echo "Dynamic Security admin password secret must not be empty." >&2
    exit 65
  fi
  case "$admin_password" in
    *[[:space:]]*)
      echo "Dynamic Security admin password must not contain whitespace." >&2
      exit 66
      ;;
  esac

  config_directory="$(dirname "$DYNSEC_CONFIG")"
  temporary_config="${DYNSEC_CONFIG}.init.$$"
  mkdir -p "$config_directory"
  rm -f "$temporary_config"
  umask 077

  mosquitto_ctrl dynsec init \
    "$temporary_config" \
    "$ADMIN_USERNAME" \
    "$admin_password" \
    >/dev/null

  chown mosquitto:mosquitto "$temporary_config"
  chmod 0600 "$temporary_config"
  mv "$temporary_config" "$DYNSEC_CONFIG"
  unset admin_password
}

initialize_dynamic_security
chown mosquitto:mosquitto "$DYNSEC_CONFIG"
chmod 0600 "$DYNSEC_CONFIG"

exec "$@"
