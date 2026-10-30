#!/bin/sh
set -eu

BROKER_HOST="${NEXOLAB_MQTT_BROKER_HOST:-127.0.0.1}"
BROKER_PORT="${NEXOLAB_MQTT_BROKER_PORT:-1883}"
ADMIN_USERNAME="${NEXOLAB_MQTT_ADMIN_USERNAME:-admin}"
ADMIN_CLIENT_ID="${NEXOLAB_MQTT_ADMIN_CLIENT_ID:-nexolab-dynsec-admin-cli}"
ADMIN_PASSWORD_FILE="${NEXOLAB_MQTT_ADMIN_PASSWORD_FILE:-/run/secrets/mqtt_admin_password}"
TLS_REQUIRED="${NEXOLAB_MQTT_TLS_REQUIRED:-false}"
TLS_CA_FILE="${NEXOLAB_MQTT_TLS_CA_FILE:-}"
TLS_CERT_FILE="${NEXOLAB_MQTT_TLS_CERT_FILE:-}"
TLS_KEY_FILE="${NEXOLAB_MQTT_TLS_KEY_FILE:-}"
TLS_ENABLED=false
CONTROL_OPTIONS=""
CONTROL_STDOUT=""
CONTROL_STDERR=""

usage() {
  cat >&2 <<'EOF'
Usage:
  nexolab-dynsec-admin bootstrap-defaults
  nexolab-dynsec-admin create-node <username> <client-id> <organization-id> <node-id> <password-file>
  nexolab-dynsec-admin create-ingestion <username> <client-id> <password-file>
  nexolab-dynsec-admin create-receipt-publisher <username> <client-id> <password-file>
  nexolab-dynsec-admin grant-node-receipts <username> <organization-id> <node-id>
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
  for path in "$CONTROL_OPTIONS" "$CONTROL_STDOUT" "$CONTROL_STDERR"; do
    if [ -n "$path" ]; then
      rm -f "$path"
    fi
  done
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

prepare_tls_options() {
  case "$TLS_REQUIRED" in
    1|true|TRUE|yes|YES|on|ON)
      TLS_ENABLED=true
      ;;
    0|false|FALSE|no|NO|off|OFF)
      if [ -n "$TLS_CA_FILE$TLS_CERT_FILE$TLS_KEY_FILE" ]; then
        echo "TLS files require NEXOLAB_MQTT_TLS_REQUIRED=true." >&2
        exit 72
      fi
      TLS_ENABLED=false
      return
      ;;
    *)
      echo "NEXOLAB_MQTT_TLS_REQUIRED must be true or false." >&2
      exit 72
      ;;
  esac

  if [ -z "$TLS_CA_FILE" ] || [ ! -r "$TLS_CA_FILE" ]; then
    echo "TLS CA file is required and must be readable." >&2
    exit 73
  fi
  if [ -n "$TLS_CERT_FILE" ] && [ -z "$TLS_KEY_FILE" ]; then
    echo "TLS client certificate and key must be configured together." >&2
    exit 74
  fi
  if [ -z "$TLS_CERT_FILE" ] && [ -n "$TLS_KEY_FILE" ]; then
    echo "TLS client certificate and key must be configured together." >&2
    exit 74
  fi
  if [ -n "$TLS_CERT_FILE" ]; then
    if [ ! -r "$TLS_CERT_FILE" ]; then
      echo "TLS client certificate file is not readable." >&2
      exit 75
    fi
    if [ ! -r "$TLS_KEY_FILE" ]; then
      echo "TLS client key file is not readable." >&2
      exit 76
    fi
  fi
}

prepare_control_options() {
  required_value "$ADMIN_USERNAME" "Admin username"
  required_value "$ADMIN_CLIENT_ID" "Admin client ID"
  prepare_tls_options
  admin_password="$(read_secret "$ADMIN_PASSWORD_FILE")"
  CONTROL_OPTIONS="$(mktemp)"
  chmod 0600 "$CONTROL_OPTIONS"
  {
    printf '%s\n' "-h $BROKER_HOST"
    printf '%s\n' "-p $BROKER_PORT"
    printf '%s\n' "-i $ADMIN_CLIENT_ID"
    printf '%s\n' "-u $ADMIN_USERNAME"
    printf '%s\n' "-P $admin_password"
    if [ "$TLS_ENABLED" = "true" ]; then
      printf '%s\n' "--cafile $TLS_CA_FILE"
      printf '%s\n' "--tls-version tlsv1.2"
      if [ -n "$TLS_CERT_FILE" ]; then
        printf '%s\n' "--cert $TLS_CERT_FILE"
        printf '%s\n' "--key $TLS_KEY_FILE"
      fi
    fi
    printf '%s\n' "--quiet"
  } >"$CONTROL_OPTIONS"
  unset admin_password
}

ctrl() {
  CONTROL_STDOUT="$(mktemp)"
  CONTROL_STDERR="$(mktemp)"
  status=0
  mosquitto_ctrl -o "$CONTROL_OPTIONS" dynsec "$@" \
    >"$CONTROL_STDOUT" 2>"$CONTROL_STDERR" || status=$?

  if [ "$status" -ne 0 ]; then
    cat "$CONTROL_STDERR" >&2
    rm -f "$CONTROL_STDOUT" "$CONTROL_STDERR"
    CONTROL_STDOUT=""
    CONTROL_STDERR=""
    return "$status"
  fi

  if [ -s "$CONTROL_STDERR" ]; then
    if grep -Eiq \
      '(^|[^[:alpha:]])(error|failed|failure|unable|refused|certificate|verification|tls)([^[:alpha:]]|$)' \
      "$CONTROL_STDERR"; then
      cat "$CONTROL_STDERR" >&2
      rm -f "$CONTROL_STDOUT" "$CONTROL_STDERR"
      CONTROL_STDOUT=""
      CONTROL_STDERR=""
      return 77
    fi
    cat "$CONTROL_STDERR" >&2
  fi

  cat "$CONTROL_STDOUT"
  rm -f "$CONTROL_STDOUT" "$CONTROL_STDERR"
  CONTROL_STDOUT=""
  CONTROL_STDERR=""
}

client_exists() {
  ctrl listClients 2>/dev/null | grep -Fqx -- "$1"
}

role_exists() {
  ctrl listRoles 2>/dev/null | grep -Fqx -- "$1"
}

client_definition() {
  ctrl getClient "$1" 2>/dev/null
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
    definition="$(client_definition "$username")"
    if ! printf '%s\n' "$definition" | grep -Fqx -- "Clientid: $client_id"; then
      echo "Dynamic Security client ID mismatch for existing client: $username" >&2
      exit 70
    fi
    return
  fi

  client_password="$(read_secret "$password_file")"
  ctrl createClient "$username" -i "$client_id" -p "$client_password" >/dev/null
  unset client_password
}

ensure_client_role() {
  username=$1
  role_name=$2
  priority=$3
  definition="$(client_definition "$username")"
  if printf '%s\n' "$definition" | grep -Fq -- "$role_name (priority: $priority)"; then
    return
  fi
  ctrl addClientRole "$username" "$role_name" "$priority" >/dev/null
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
  ensure_client_role "$username" "$role_name" 100
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
  ensure_client_role "$username" "$role_name" 100
}


# Explicit receipt grants only. The standard create-node and create-ingestion
# commands never enable receipt publishing or subscribing.
receipt_acls() {
  ctrl getRole "$1" | awk '
    /^ACLs:/ {active=1; sub(/^ACLs:[[:space:]]*/, ""); if(length($0)) print; next}
    active && /^[[:alpha:]][[:alnum:]_]*:/ {exit}
    active {if(length($0)) print}
  ' | sed 's/[[:space:]]//g' | sed '/^$/d' | sort
}
receipt_members() {
  printf '%s\n' "$1" | awk -v wanted="$2" '
    $0 ~ ("^" wanted ":") {
      active=1; sub(/^[^:]*:[[:space:]]*/, "")
      if(length($0)) print
      next
    }
    active && /^[[:alpha:]][[:alnum:]_]*:/ {exit}
    active {sub(/^[[:space:]]+/, ""); if(length($0)) print}
  ' | sort
}
verify_receipt_role() {
  [ "$(receipt_acls "$1")" = "$2" ] || {
    echo "Unexpected existing receipt-role ACL; refusing." >&2
    exit 79
  }
}
verify_receipt_client() {
  detail="$(client_definition "$1")"
  [ "$(receipt_members "$detail" Roles)" = "$2" ] &&
    [ -z "$(receipt_members "$detail" Groups)" ] &&
    printf '%s\n' "$detail" | grep -Eq '^Disabled:[[:space:]]*false' || {
    echo "Unexpected receipt client roles/groups/status; refusing." >&2
    exit 80
  }
}
create_receipt_publisher() {
  user=$1
  cid=$2
  secret=$3
  required_value "$user" "Receipt publisher username"
  required_value "$cid" "Receipt publisher client-id"
  case "$user" in
    "$ADMIN_USERNAME"|nexolab-central-ingestion|node:*)
      echo "Dedicated receipt principal required." >&2; exit 81 ;;
  esac
  [ "$cid" != "$ADMIN_CLIENT_ID" ] &&
    [ "$cid" != "nexolab-central-ingestion" ] || {
    echo "Dedicated receipt client-id required." >&2; exit 81;
  }
  role=nexolab-central-receipts-only
  exact=publishClientSend:allow:nexolab/v1/+/+/receipts(priority:100)
  if role_exists "$role"; then
    verify_receipt_role "$role" "$exact"
  else
    ctrl createRole "$role" >/dev/null
    ctrl addRoleACL "$role" publishClientSend "nexolab/v1/+/+/receipts" allow 100 >/dev/null
    verify_receipt_role "$role" "$exact"
  fi
  member="$role (priority: 100)"
  if client_exists "$user"; then
    cid_existing="$(client_definition "$user" | sed -n 's/^Clientid:[[:space:]]*//p')"
    [ "$cid_existing" = "$cid" ] || {
      echo "Existing receipt principal/client-id mismatch." >&2; exit 80;
    }
    verify_receipt_client "$user" "$member"
  else
    create_client "$user" "$cid" "$secret"
    ensure_client_role "$user" "$role" 100
    verify_receipt_client "$user" "$member"
  fi
}
grant_node_receipts() {
  user=$1
  org=$2
  node=$3
  printf '%s\n' "$org" | grep -Eq \
    '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[ -n "$command" ] || usage
shift
prepare_control_options

case "$command" in
  create-receipt-publisher)
    [ "$#" -eq 3 ] || usage
    create_receipt_publisher "$1" "$2" "$3"
    ;;
  grant-node-receipts)
    [ "$#" -eq 3 ] || usage
    grant_node_receipts "$1" "$2" "$3"
    ;;
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
 || {
    echo "Noncanonical organization ID." >&2; exit 78;
  }
  [ "$(printf %s "$node" | wc -c)" -le 64 ] &&
    printf '%s\n' "$node" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?[ -n "$command" ] || usage
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
 || {
    echo "Unsafe node receipt identity." >&2; exit 78;
  }
  [ "$user" = "node:$org:$node" ] && client_exists "$user" || {
    echo "Unprovisioned or mismatched receipt node." >&2; exit 81;
  }
  detail="$(client_definition "$user")"
  cid_existing="$(printf '%s\n' "$detail" | sed -n 's/^Clientid:[[:space:]]*//p')"
  [ "$cid_existing" = "nexolab-$org-$node" ] || {
    echo "Node receipt client-id mismatch." >&2; exit 80;
  }
  old="nexolab-node-$org-$node (priority: 100)"
  role="nexolab-node-receipts-$org-$node"
  new="$role (priority: 100)"
  together="$(printf '%s\n%s\n' "$old" "$new" | sort)"
  memberships="$(receipt_members "$detail" Roles)"
  [ -z "$(receipt_members "$detail" Groups)" ] &&
    { [ "$memberships" = "$old" ] || [ "$memberships" = "$together" ]; } || {
    echo "Node role/group mismatch." >&2; exit 80;
  }
  topic="nexolab/v1/$org/$node/receipts"
  exact="$(printf '%s\n' \
    "subscribeLiteral:allow:$topic(priority:100)" \
    "unsubscribeLiteral:allow:$topic(priority:100)" \
    "publishClientReceive:allow:$topic(priority:100)" | sort)"
  if role_exists "$role"; then
    verify_receipt_role "$role" "$exact"
  else
    ctrl createRole "$role" >/dev/null
    ctrl addRoleACL "$role" subscribeLiteral "$topic" allow 100 >/dev/null
    ctrl addRoleACL "$role" unsubscribeLiteral "$topic" allow 100 >/dev/null
    ctrl addRoleACL "$role" publishClientReceive "$topic" allow 100 >/dev/null
    verify_receipt_role "$role" "$exact"
  fi
  if [ "$memberships" = "$old" ]; then
    ctrl addClientRole "$user" "$role" 100 >/dev/null
  fi
  verify_receipt_client "$user" "$together"
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
