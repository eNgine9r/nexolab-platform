# MQTT broker-control outbox operations

This runbook covers the application-managed synchronization between the NEXOLAB Node Registry and Mosquitto Dynamic Security. It complements `mqtt-dynamic-security.md`: operators use the Node Registry API and `/nodes` workspace for normal lifecycle changes instead of running broker commands manually.

## Safety boundary

- Node provisioning and credential rotation place the one-time password in an AES-256-GCM encrypted PostgreSQL outbox command.
- Suspension, reactivation and revocation use secret-free `disable`, `enable` and `delete` commands.
- The worker never places node passwords in environment variables, argv, structured logs, audit snapshots or REST responses.
- A broker operation is not considered synchronized until the command state is `applied` and the broker response matches the exact expected identity/state.
- Physical credential installation, TLS and two-Raspberry-Pi reconnect validation remain deferred hardware Gates.

## Required mounted secrets

The secure central overlay expects this directory outside the repository:

```text
/opt/nexolab/secrets/mqtt-central/
├── admin-password
├── ingestion-password
└── broker-control-key
```

Recommended ownership and permissions:

```bash
sudo install -d -m 0700 -o root -g root /opt/nexolab/secrets/mqtt-central
sudo chmod 0600 /opt/nexolab/secrets/mqtt-central/*
```

`admin-password` and `ingestion-password` contain one non-empty password without whitespace or a trailing newline.

Generate the broker-control envelope key once:

```bash
umask 077
python3 - <<'PY' > /opt/nexolab/secrets/mqtt-central/broker-control-key
import base64
import secrets
print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"), end="")
PY
chmod 0600 /opt/nexolab/secrets/mqtt-central/broker-control-key
```

The file must decode to exactly 32 bytes. Do not print, copy into `.env`, commit or attach it to evidence.

## Environment contract

Start from `infrastructure/compose/.env.mqtt-security.example`. The environment contains identities, file locations, key ID and retry tuning only.

Important values:

```bash
MQTT_SECURITY_SECRETS_DIR=/opt/nexolab/secrets/mqtt-central
BROKER_CONTROL_ENCRYPTION_KEY_ID=broker-control-v1
BROKER_CONTROL_ADMIN_CLIENT_ID=nexolab-broker-control-worker
BROKER_CONTROL_MAX_ATTEMPTS=8
BROKER_CONTROL_RETRY_INITIAL_SECONDS=1
BROKER_CONTROL_RETRY_MAX_SECONDS=300
BROKER_CONTROL_COMMAND_TIMEOUT_SECONDS=15
BROKER_CONTROL_STALE_LOCK_SECONDS=60
```

`BROKER_CONTROL_STALE_LOCK_SECONDS` must be greater than `BROKER_CONTROL_COMMAND_TIMEOUT_SECONDS`.

## Validate and start the secure control plane

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.mqtt-security \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  config --quiet

docker compose \
  --env-file .env.mqtt-security \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  up -d --build
```

Verify:

```bash
docker compose \
  --env-file .env.mqtt-security \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  ps

curl -fsS http://127.0.0.1:8082/health/ready
```

The telemetry image contains `mosquitto_ctrl` and a byte-identical copy of the hardened `nexolab-dynsec-admin` executable. CI rejects script drift.

## Lifecycle mapping

| Node Registry action        | Outbox operation | Secret material                | Expected broker result                             |
| --------------------------- | ---------------- | ------------------------------ | -------------------------------------------------- |
| Provision                   | `provision`      | encrypted one-time password    | exact username, client ID and node role            |
| Rotate credential           | `rotate`         | encrypted replacement password | exact client ID with new password                  |
| Suspend                     | `disable`        | none                           | client disabled and active connection disconnected |
| Reactivate after suspension | `enable`         | none                           | exact client ID enabled                            |
| Revoke                      | `delete`         | none                           | client absent and active connection disconnected   |

Initial `pending → active` does not enqueue `enable`; the provisioning command creates an enabled client. Only `suspended → active` needs `enable`.

## Reconciliation endpoint

```text
GET /api/v1/nodes/{node_id}/broker-control
```

It requires `nodes.read`, is organization-scoped and returns nondisclosing `404` for another organization.

Safe response fields include:

- desired broker state;
- synchronization state;
- operation and command state;
- attempts and timestamps;
- sanitized error code/detail.

The response never contains ciphertext, nonce, encryption key ID, deduplication key, command digest or credentials.

Synchronization states:

| State         | Meaning                                           | Operator action                             |
| ------------- | ------------------------------------------------- | ------------------------------------------- |
| `pending`     | durable command has not been claimed              | wait for the worker                         |
| `processing`  | a worker lease is active                          | observe; stale leases recover automatically |
| `retrying`    | retryable broker/transport failure                | restore broker connectivity                 |
| `applied`     | strict broker reconciliation passed               | no action                                   |
| `failed`      | terminal error or attempt limit                   | inspect safe error evidence and remediate   |
| `out_of_sync` | latest applied operation conflicts with lifecycle | investigate before installing credentials   |
| `disabled`    | broker control is not enabled                     | use the secure Compose overlay              |

The `/nodes` operator panel refreshes reconciliation every five seconds.

## Broker outage and restart recovery

A broker outage does not lose a one-time node secret:

1. Node lifecycle transaction commits the credential hash, audit event and encrypted outbox command atomically.
2. The worker marks transport failures `retrying` with bounded exponential delay.
3. Restarting telemetry-service preserves the command in PostgreSQL.
4. When the broker returns, the worker reclaims and applies the command.
5. A command left in `processing` after a crash is returned to `retrying` after the stale-lock interval.

Do not manually change an outbox row to `applied`.

Inspect safe command state:

```sql
SELECT organization_id, node_id, operation, state, attempts,
       available_at, last_attempt_at, applied_at, failed_at,
       error_code, error_detail
FROM central_node_broker_commands
ORDER BY created_at DESC;
```

Do not select or export encrypted envelope columns during routine evidence collection.

## Terminal failures

Typical terminal evidence:

- `broker_control_envelope_invalid`: ciphertext/key mismatch or authentication failure;
- `broker_command_rejected`: invalid identity or client-ID drift;
- `broker_response_invalid`: malformed/unexpected admin response;
- `broker_reconciliation_mismatch`: broker state did not match the command;
- `broker_admin_unavailable`: packaged executable or mounted admin secret unavailable.

Never copy ciphertext into tickets or chat. Record command ID, node ID, operation, safe error code and timestamps.

## Envelope key rotation

Existing pending/retrying commands are encrypted with their recorded key ID. The current implementation loads one active key at startup and therefore fails closed when an older key ID is unavailable.

Controlled rotation procedure:

1. Ensure no commands are `pending`, `processing` or `retrying`.
2. Back up PostgreSQL and Dynamic Security state.
3. Generate a new 32-byte base64url key into a new file.
4. Atomically replace `broker-control-key` and update `BROKER_CONTROL_ENCRYPTION_KEY_ID`.
5. Recreate telemetry-service.
6. Provision a controlled test node and verify `applied`.
7. Retain the old key through the approved recovery window, outside the active mount.

Do not rotate the key while encrypted commands are outstanding.

## Acceptance Gate

Run without Raspberry Pi or physical network access:

```bash
cd ~/nexolab-platform
bash scripts/run-broker-control-acceptance.sh
```

The Gate uses isolated PostgreSQL and secure Mosquitto volumes and verifies:

- durable retry during broker outage;
- telemetry-service restart recovery;
- exact provisioning replay;
- password rotation and old-password rejection;
- suspension disconnect and reconnect denial;
- reactivation through `enable`;
- revocation through idempotent `delete`;
- organization isolation;
- production Chromium reconciliation UI;
- absence of plaintext secrets from database, logs and Dynamic Security persistence.

Evidence is written to `test-results-broker-control`. The temporary secret directory is removed and is never uploaded.

## Rollback

Stop the secure overlay without deleting named volumes:

```bash
docker compose \
  --env-file .env.mqtt-security \
  -f compose.central.yaml \
  -f compose.central-mqtt-security.yaml \
  down --remove-orphans
```

Never add `--volumes` or `-v` during rollback. Reverting to the anonymous base broker weakens security and must be treated as an incident with restricted network exposure.
