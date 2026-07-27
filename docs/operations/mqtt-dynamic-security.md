# MQTT Dynamic Security operations

This runbook enables per-node MQTT authentication on the central NEXOLAB broker without deleting existing PostgreSQL, MinIO or MQTT named volumes.

The secure profile is an explicit Compose overlay. The base central profile remains the emergency rollback path until TLS and the physical two-node pilot are validated.

## Security model

- Anonymous central MQTT connections are rejected.
- The central telemetry service has one ingestion identity.
- Each edge node has one username, one exact MQTT client ID and one password.
- A node can publish only to its exact `telemetry`, `health` and `status` topics.
- Nodes cannot subscribe to application topics or `$SYS/#`.
- The ingestion identity can subscribe/receive, but cannot publish node traffic.
- Application-level organization, lifecycle and replay validation remains enabled as defense in depth.

## Secret directories

Create secrets outside the repository:

```text
/opt/nexolab/secrets/mqtt-central/
├── admin-password
├── ingestion-password
├── edge-01-password
└── edge-02-password

/opt/nexolab/secrets/mqtt-edge-01/
└── node-password

/opt/nexolab/secrets/mqtt-edge-02/
└── node-password
```

Requirements:

- directories mode `0700`;
- files mode `0600`;
- one non-empty secret per file;
- no whitespace or newline inside a secret;
- files are never committed, printed or attached to evidence archives.

Generate a secret locally:

```bash
umask 077
python3 - <<'PY' > /opt/nexolab/secrets/mqtt-central/admin-password
import secrets
print("nxl_mqtt_" + secrets.token_urlsafe(48), end="")
PY
```

Repeat for ingestion and node passwords. Transfer a node password to its edge host through an approved secure channel.

## Required environment

```bash
export POSTGRES_PASSWORD='...'
export MINIO_ROOT_USER='...'
export MINIO_ROOT_PASSWORD='...'
export MQTT_ADMIN_USERNAME='nexolab-security-admin'
export MQTT_INGESTION_USERNAME='nexolab-central-ingestion'
export MQTT_INGESTION_CLIENT_ID='nexolab-central-ingestion'
export MQTT_SECURITY_SECRETS_DIR='/opt/nexolab/secrets/mqtt-central'
export MQTT_NODE_REGISTRY_ENFORCED='true'
```

Do not place plaintext MQTT passwords in the environment. Only file paths are passed to containers.

## Validate merged Compose configuration

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  config --quiet
```

## Start or reconcile the secure central broker

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  up -d --build
```

The init service is idempotent. It applies default-deny ACLs and reconciles the central ingestion role without rotating its existing password.

Verify:

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  ps

curl -fsS http://127.0.0.1:8082/health/ready
```

## Provision one edge node

Example values:

```bash
export ORGANIZATION_ID='00000000-0000-0000-0000-000000000001'
export NODE_ID='edge-01'
export NODE_USERNAME="node:${ORGANIZATION_ID}:${NODE_ID}"
export NODE_CLIENT_ID="nexolab-${ORGANIZATION_ID}-${NODE_ID}"
```

Provision or reconcile:

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  exec -T mqtt \
  /usr/local/bin/nexolab-dynsec-admin create-node \
  "$NODE_USERNAME" \
  "$NODE_CLIENT_ID" \
  "$ORGANIZATION_ID" \
  "$NODE_ID" \
  "/run/secrets/nexolab/${NODE_ID}-password"
```

A repeated command verifies the existing client ID and reconciles role ACLs. It does not silently rotate credentials or re-enable a disabled client.

## Configure the edge bridge

On the edge host:

```bash
export CENTRAL_MQTT_HOST='central-host-or-address'
export CENTRAL_MQTT_PORT='1884'
export NEXOLAB_ORGANIZATION_ID='00000000-0000-0000-0000-000000000001'
export NEXOLAB_NODE_ID='edge-01'
export CENTRAL_BRIDGE_CLIENT_ID="nexolab-${NEXOLAB_ORGANIZATION_ID}-${NEXOLAB_NODE_ID}"
export CENTRAL_MQTT_USERNAME="node:${NEXOLAB_ORGANIZATION_ID}:${NEXOLAB_NODE_ID}"
export MQTT_NODE_SECRETS_DIR='/opt/nexolab/secrets/mqtt-edge-01'
```

Validate and start:

```bash
docker compose \
  -f compose.edge.yaml \
  -f compose.edge-central-bridge.yaml \
  -f compose.edge-central-security.yaml \
  config --quiet

docker compose \
  -f compose.edge.yaml \
  -f compose.edge-central-bridge.yaml \
  -f compose.edge-central-security.yaml \
  up -d --force-recreate mqtt device-agent
```

The bridge forwards only the exact node telemetry, health and status topics.

## Rotate one node password

1. Generate the replacement secret into a temporary file with mode `0600`.
2. Copy it securely to the edge host as a temporary file.
3. Replace the central secret file atomically.
4. Execute rotation:

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  exec -T mqtt \
  /usr/local/bin/nexolab-dynsec-admin rotate-password \
  "$NODE_USERNAME" \
  "/run/secrets/nexolab/${NODE_ID}-password"
```

5. Replace the edge `node-password` atomically and recreate the edge bridge.
6. Verify health and queue recovery.
7. Destroy old secret material.

The previous password becomes invalid immediately.

## Disable or re-enable a node

Disable:

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  exec -T mqtt \
  /usr/local/bin/nexolab-dynsec-admin disable-client "$NODE_USERNAME"
```

Enable only after an explicit operational decision:

```bash
docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  exec -T mqtt \
  /usr/local/bin/nexolab-dynsec-admin enable-client "$NODE_USERNAME"
```

Disabled clients cannot reconnect. Keep the application registry credential suspended/revoked as defense in depth.

## Backup Dynamic Security state

The state is stored in the named MQTT volume as `dynamic-security.json`. Back it up together with broker persistence while the broker is stopped or through a storage-consistent snapshot.

Never copy the file into the repository. It contains password hashes, client identities, roles and ACL policy.

## Emergency rollback

Rollback does not delete named volumes:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  down --remove-orphans

docker compose -f compose.central.yaml up -d
```

This restores the previous anonymous central broker profile and therefore weakens security. Record the rollback as an incident, restrict network reachability and return to the secure profile after remediation.

Never use `docker compose down --volumes` during production rollback.

## Deferred physical Gate

The following remain deferred until the actual central host and Raspberry Pi nodes are available:

- TLS certificates and hostname verification;
- LAN/VLAN firewall rules;
- secure installation of node credentials on real edge hosts;
- unexpected network loss and reconnect with two Raspberry Pi nodes;
- broker certificate rotation;
- Tailscale/LAN exposure validation.
