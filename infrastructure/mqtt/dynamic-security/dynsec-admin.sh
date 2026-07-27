#!/bin/sh
set -eu

BROKER_HOST="${NEXOLAB_MQTT_BROKER_HOST:-127.0.0.1}"
BROKER_PORT="${NEXOLAB_MQTT_BROKER_PORT:-1883}"
ADMIN_USERNAME="${NEXOLAB_MQTT_ADMIN_USERNAME:-admin}"
ADMIN_CLIENT_ID="${NEXOLAB_MQTT_ADMIN_CLIENT_ID:-nexolab-dynsec-admin-cli}"
ADMIN_PASSWORD_FILE="${NEXOLAB_MQTT_ADMIN_PASSWORD_FILE:-/run/secrets/mqtt_admin_password}"
CONTROL_OPTIONS=""

usage() {
  cat >&2 <<'EOF'
Usage:
  nexolab-dynsec-admin bootstrap-defaults
  nexolab-dynsec-admin create-node <username> <client-id> <organization-id> <node-id> <password-file>
  nexolab-dynsec-admin create-ingestion <username> <client-id> <password-file>
  nexolab-dynsec-admin rotate-password <username> <password-file>
  nexolab-dynsec-admin disable-client <username>
  nexolab-dynsec-admin enable-client <username>
  nexolab-dynsec-admin delete-client <username>
  nexolab-dynsec-admin get-client <username>
  nexolab-dynsec-admin list-clients
EOF
  exit 64
}

cleanup() {
  if [ -n "$CONTROL_OPTIONS" ]; then
    rm -f "$CONTROL_OPTIONS"
  fi
}
trap cleanup EXIT INT TERM

required_value() {
  value=$1
  label=$2
  if [ -z "$value" ]; then
    echo "$label is required." >&2
    exit 65
  fi
  case "$value" in
    *[[:space:]]*)
      echo "$label must not contain whitespace." >&2
      exit 66
      ;;
  esac
}

read_secret() {
  secret_file=$1
  if [ ! -r "$secret_file" ]; then
    echo "Secret file is not readable: $secret_file" >&2
    exit 67
  fi
  secret_value="$(tr -d '\r\n' <"$secret_file")"
  if [ -z "$secret_value" ]; then
    echo "Secret file must not be empty: $secret_file" >&2
    exit 68
  fi
  case "$secret_value" in
    *[[:space:]]*)
      echo "Secret must not contain whitespace." >&2
      exit 69
      ;;
  esac
  printf '%s' "$secret_value"
}

prepare_control_options() {
  required_value "$ADMIN_USERNAME" "Admin username"
  required_value "$ADMIN_CLIENT_ID" "Admin client ID"
  admin_password="$(read_secret "$ADMIN_PASSWORD_FILE")"
  CONTROL_OPTIONS="$(mktemp)"
  chmod 0600 "$CONTROL_OPTIONS"
  {
    printf '%s\n' "-h $BROKER_HOST"
    printf '%s\n' "-p $BROKER_PORT"
    printf '%s\n' "-i $ADMIN_CLIENT_ID"
    printf '%s\n' "-u $ADMIN_USERNAME"
    printf '%s\n' "-P $admin_password"
    printf '%s\n' "--quiet"
  } >"$CONTROL_OPTIONS"
  unset admin_password
}

ctrl() {
  mosquitto_ctrl -o "$CONTROL_OPTIONS" dynsec "$@"
}

client_exists() {
  ctrl listClients 2>/dev/null | grep -Fqx -- "$1"
}

role_exists() {
  ctrl listRoles 2>/dev/null | grep -Fqx -- "$1"
}

ensure_role() {
  role_name=$1
  if ! role_exists "$role_name"; then
    ctrl createRole "$role_name" >/dev/null
  fi
}

replace_role_acl() {
  role_name=$1
  acl_type=$2
  topic_filter=$3
  access=$4
  priority=$5
  ctrl removeRoleACL "$role_name" "$acl_type" "$topic_filter" >/dev/null 2>&1 || true
  ctrl addRoleACL "$role_name" "$acl_type" "$topic_filter" "$access" "$priority" >/dev/null
}

create_client() {
  username=$1
  client_id=$2
  password_file=$3
  required_value "$username" "Client username"
  required_value "$client_id" "Client ID"
  if client_exists "$username"; then
    echo "Dynamic Security client already exists: $username" >&2
    exit 70
  fi
  client_password="$(read_secret "$password_file")"
  ctrl createClient "$username" -i "$client_id" -p "$client_password" >/dev/null
  unset client_password
}

set_client_password() {
  username=$1
  password_file=$2
  required_value "$username" "Client username"
  if ! client_exists "$username"; then
    echo "Dynamic Security client does not exist: $username" >&2
    exit 71
  fi
  client_password="$(read_secret "$password_file")"
  ctrl setClientPassword "$username" "$client_password" >/dev/null
  unset client_password
}

bootstrap_defaults() {
  ctrl setDefaultACLAccess publishClientSend deny >/dev/null
  ctrl setDefaultACLAccess publishClientReceive deny >/dev/null
  ctrl setDefaultACLAccess subscribe deny >/dev/null
  ctrl setDefaultACLAccess unsubscribe deny >/dev/null
}

create_node() {
  username=$1
  client_id=$2
  organization_id=$3
  node_id=$4
  password_file=$5
  required_value "$organization_id" "Organization ID"
  required_value "$node_id" "Node ID"

  role_name="nexolab-node-${organization_id}-${node_id}"
  ensure_role "$role_name"
  replace_role_acl "$role_name" publishClientSend \
    "nexolab/v1/${organization_id}/${node_id}/telemetry" allow 100
  replace_role_acl "$role_name" publishClientSend \
    "nexolab/v1/${organization_id}/${node_id}/health" allow 100
  replace_role_acl "$role_name" publishClientSend \
    "nexolab/v1/${organization_id}/${node_id}/status" allow 100

  create_client "$username" "$client_id" "$password_file"
  ctrl addClientRole "$username" "$role_name" 100 >/dev/null
}

create_ingestion() {
  username=$1
  client_id=$2
  password_file=$3
  role_name="nexolab-central-ingestion"

  ensure_role "$role_name"
  for stream in telemetry health status; do
    topic_filter="nexolab/v1/+/+/${stream}"
    replace_role_acl "$role_name" subscribePattern "$topic_filter" allow 100
    replace_role_acl "$role_name" unsubscribePattern "$topic_filter" allow 100
    replace_role_acl "$role_name" publishClientReceive "$topic_filter" allow 100
  done

  create_client "$username" "$client_id" "$password_file"
  ctrl addClientRole "$username" "$role_name" 100 >/dev/null
}

command=${1:-}
[ -n "$command" ] || usage
shift
prepare_control_options

case "$command" in
  bootstrap-defaults)
    [ "$#" -eq 0 ] || usage
    bootstrap_defaults
    ;;
  create-node)
    [ "$#" -eq 5 ] || usage
    create_node "$1" "$2" "$3" "$4" "$5"
    ;;
  create-ingestion)
    [ "$#" -eq 3 ] || usage
    create_ingestion "$1" "$2" "$3"
    ;;
  rotate-password)
    [ "$#" -eq 2 ] || usage
    set_client_password "$1" "$2"
    ;;
  disable-client)
    [ "$#" -eq 1 ] || usage
    ctrl disableClient "$1" >/dev/null
    ;;
  enable-client)
    [ "$#" -eq 1 ] || usage
    ctrl enableClient "$1" >/dev/null
    ;;
  delete-client)
    [ "$#" -eq 1 ] || usage
    ctrl deleteClient "$1" >/dev/null
    ;;
  get-client)
    [ "$#" -eq 1 ] || usage
    ctrl getClient "$1"
    ;;
  list-clients)
    [ "$#" -eq 0 ] || usage
    ctrl listClients
    ;;
  *)
    usage
    ;;
esac
