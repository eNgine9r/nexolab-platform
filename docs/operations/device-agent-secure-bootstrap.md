# Secure Device Agent bootstrap and fleet recovery

This runbook covers the edge-side connection between NEXOLAB Device Agent and the central Mosquitto Dynamic Security control plane.

The procedure does not require direct Raspberry Pi access for CI acceptance. Installation on physical Raspberry Pi nodes, TLS hostname validation and real Ethernet outage testing remain separate hardware Gates.

## Security boundary

A secure Device Agent identity consists of three exact values:

| Field     | Contract                                                    |
| --------- | ----------------------------------------------------------- |
| Username  | `node:{organization_id}:{node_id}`                          |
| Client ID | `nexolab-{organization_id}-{node_id}`                       |
| Password  | One-time Node Registry secret stored only in a mounted file |

Secure mode is enabled with:

```text
MQTT_AUTH_REQUIRED=true
```

When secure mode is enabled, startup fails closed if:

- `NEXOLAB_ORGANIZATION_ID` is missing;
- the username does not match the organization and node;
- the client ID does not match the organization and node;
- the password file is missing or unreadable;
- the password is empty;
- the password contains whitespace or control characters.

The password must not be placed in `.env`, Docker environment variables, process arguments, health responses, logs or evidence artifacts.

## Prepare the edge secret

Create a dedicated directory outside the repository:

```bash
sudo install -d -m 0700 -o root -g root /opt/nexolab/secrets/edge-01
```

Provision the node through the Node Registry API or operator workspace. The plaintext secret is returned once. Write it directly into a temporary file and atomically install it:

```bash
umask 077
printf '%s' '<one-time-node-secret>' > /tmp/nexolab-edge-01-password
sudo install -m 0600 -o root -g root \
  /tmp/nexolab-edge-01-password \
  /opt/nexolab/secrets/edge-01/mqtt-password
rm -f /tmp/nexolab-edge-01-password
```

Do not paste the secret into tickets, chat, shell history or committed files.

## Configure the secure profile

Start from the example:

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.edge-secure.example .env.edge-secure
chmod 0600 .env.edge-secure
```

Set the exact non-secret identity fields:

```text
NEXOLAB_ORGANIZATION_ID=00000000-0000-0000-0000-000000000001
NEXOLAB_NODE_ID=edge-01
MQTT_USERNAME=node:00000000-0000-0000-0000-000000000001:edge-01
MQTT_CLIENT_ID=nexolab-00000000-0000-0000-0000-000000000001-edge-01
CENTRAL_MQTT_HOST=192.168.1.10
CENTRAL_MQTT_PORT=1883
EDGE_MQTT_PASSWORD_FILE=/opt/nexolab/secrets/edge-01/mqtt-password
EDGE_DATA_VOLUME=nexolab-edge-01-data
```

The central broker address must be reachable only through the trusted laboratory network or VPN. Plain MQTT on port 1883 must not be exposed publicly.

## Validate and start

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  config --quiet

docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  up -d
```

For a physical Modbus node, add the hardware override only during the explicit hardware Gate:

```bash
docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  -f compose.hardware.yaml \
  up -d
```

## Verify runtime state

```bash
curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool
```

Expected secure healthy state:

```json
{
  "status": "ok",
  "mqtt_connected": true,
  "queue_depth": 0
}
```

The health response must not contain username, client ID, password, password path or secret fingerprint.

Inspect container state without printing environment secrets:

```bash
docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  ps

docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  logs --tail 100 device-agent
```

## Broker outage and backlog recovery

During broker unavailability:

1. Device Agent continues sampling.
2. New events are appended to the persistent SQLite queue.
3. Restarting the container does not remove the queue or stream sequence.
4. After reconnect, queued events are published in FIFO order.
5. New samples remain behind an existing backlog until older events are delivered.
6. Central storage deduplicates exact event replay by `event_id`.

Observe queue growth and recovery:

```bash
watch -n 1 'curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool'
```

Do not delete the named edge data volume during an outage.

## Credential rotation

Use a controlled maintenance window because the old password becomes invalid for the next connection attempt.

1. Rotate the credential through Node Registry.
2. Capture the new one-time secret without logging it.
3. Write the secret to a temporary mode-0600 file.
4. Atomically replace the mounted password file.
5. Recreate Device Agent.
6. Verify MQTT reconnect and queue drain.
7. Verify the other nodes remain online.

Example atomic replacement:

```bash
umask 077
printf '%s' '<rotated-one-time-secret>' > /tmp/nexolab-edge-01-password
sudo install -m 0600 -o root -g root \
  /tmp/nexolab-edge-01-password \
  /opt/nexolab/secrets/edge-01/mqtt-password.new
sudo mv \
  /opt/nexolab/secrets/edge-01/mqtt-password.new \
  /opt/nexolab/secrets/edge-01/mqtt-password
rm -f /tmp/nexolab-edge-01-password

docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  up -d --force-recreate device-agent
```

Verify:

```bash
curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool
```

Expected result:

- `mqtt_connected` becomes `true`;
- `queue_depth` returns to `0`;
- `/nodes` shows `Online`;
- broker reconciliation shows `Синхронізовано`;
- the rotated node shows latest command `rotate · applied`;
- unaffected nodes continue publishing.

## Failure diagnosis

| Symptom                               | Likely cause                                                  | Action                                                            |
| ------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------- |
| Startup exits immediately             | Missing organization, identity drift or invalid password file | Recheck exact identity and mounted path                           |
| `mqtt_connected=false` after rotation | Old password remains mounted                                  | Atomically install the new secret and recreate the container      |
| Queue grows on every node             | Central broker or network unavailable                         | Restore broker/network; do not delete SQLite volumes              |
| Queue grows on one node only          | Node credential or identity mismatch                          | Compare Node Registry identity with `.env.edge-secure`            |
| Central telemetry rejects samples     | Payload schema or sequence contract mismatch                  | Inspect sanitized telemetry-service logs and Device Agent version |
| `/nodes` reports stale                | Health stream is not reaching central ingestion               | Check MQTT ACL, credentials and broker connectivity               |

## Rollback

Stop the secure edge service without deleting the named SQLite volume:

```bash
docker compose \
  --env-file .env.edge-secure \
  -f compose.edge-secure.yaml \
  down --remove-orphans
```

Never use `--volumes` or `-v` during routine rollback. Removing the volume destroys the offline queue and stream counters.

Do not fall back to an anonymous broker profile on a production laboratory network. Treat that change as a security incident requiring restricted network exposure.

## Automated acceptance

Run the complete software-only Gate:

```bash
cd ~/nexolab-platform
bash scripts/run-device-agent-fleet-acceptance.sh
```

The Gate verifies:

- exact per-node MQTT identities;
- two real Device Agent containers;
- broker outage queue growth;
- queue persistence across Device Agent restart;
- FIFO backlog drain;
- independent contiguous sequences;
- zero duplicate telemetry events;
- one-node credential rotation;
- unaffected-node continuity;
- production `/nodes` browser state;
- absence of plaintext credentials from PostgreSQL, SQLite, logs and container metadata.
