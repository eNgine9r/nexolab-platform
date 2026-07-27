#!/bin/sh
set -eu

SYSTEM_MOSQUITTO_PUB=/usr/bin/mosquitto_pub

if [ "${1:-}" != "-o" ]; then
  exec "$SYSTEM_MOSQUITTO_PUB" "$@"
fi

if [ "$#" -lt 2 ]; then
  echo "mosquitto_pub compatibility wrapper requires a config file after -o." >&2
  exit 64
fi

config_file=$2
shift 2

if [ ! -r "$config_file" ]; then
  echo "mosquitto_pub config file is not readable." >&2
  exit 67
fi

config_home="$(mktemp -d)"
cleanup() {
  rm -rf "$config_home"
}
trap cleanup EXIT INT TERM

install -m 0600 "$config_file" "$config_home/mosquitto_pub"
XDG_CONFIG_HOME="$config_home" "$SYSTEM_MOSQUITTO_PUB" "$@"
