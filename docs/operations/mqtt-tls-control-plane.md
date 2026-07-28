# MQTT TLS control-plane runbook

## Purpose

This runbook operates the encrypted MQTT transport used by:

- NEXOLAB Device Agent publishers;
- telemetry-service ingestion;
- the broker-control Dynamic Security administrator;
- Mosquitto on the central gateway.

TLS is fail closed. A missing CA, unreadable file, certificate hostname mismatch,
untrusted issuer, incomplete client certificate/key pair, or unavailable TLS
listener must stop the affected client. Do not use an insecure hostname bypass and
do not restore service by opening plaintext port `1883`.

## Trust and identity contract

The production certificate must satisfy all of the following:

- signed by the laboratory MQTT CA or a CA present in the mounted trust bundle;
- `basicConstraints = CA:FALSE`;
- `extendedKeyUsage = serverAuth`;
- a DNS Subject Alternative Name matching the exact `MQTT_HOST` used by every
  client;
- a validity period monitored before expiry;
- a private key stored only on the broker host.

The CA certificate must have `CA:TRUE` and `keyCertSign`. The CA private key must
not be copied to the broker, Device Agent, telemetry-service, container image,
repository, logs, evidence bundle, or browser environment.

The current software acceptance identity is:

```text
broker DNS identity: mqtt
TLS listener:         8883
plaintext listener:   absent
minimum TLS version:  TLS 1.2
```

A physical deployment must replace `mqtt` with a stable laboratory DNS hostname
and issue a certificate containing that exact hostname in the SAN extension.

## Recommended file layout

### Central broker host

```text
/opt/nexolab/secrets/mqtt/
├── ca-bundle.pem
├── server.pem
└── server.key
```

Recommended ownership and permissions:

```bash
sudo chown root:root /opt/nexolab/secrets/mqtt/ca-bundle.pem
sudo chown root:mosquitto /opt/nexolab/secrets/mqtt/server.pem
sudo chown root:mosquitto /opt/nexolab/secrets/mqtt/server.key
sudo chmod 0444 /opt/nexolab/secrets/mqtt/ca-bundle.pem
sudo chmod 0440 /opt/nexolab/secrets/mqtt/server.pem
sudo chmod 0440 /opt/nexolab/secrets/mqtt/server.key
```

### Edge node

```text
/opt/nexolab/secrets/<node-id>/
├── mqtt-password
└── mqtt-ca.pem
```

The password and CA must be mounted read-only. The Device Agent does not need the
broker private key.

## Required runtime configuration

### Device Agent

```text
MQTT_AUTH_REQUIRED=true
MQTT_TLS_REQUIRED=true
MQTT_HOST=<exact certificate DNS name>
MQTT_PORT=8883
MQTT_USERNAME=node:<organization-id>:<node-id>
MQTT_CLIENT_ID=nexolab-<organization-id>-<node-id>
MQTT_PASSWORD_FILE=/run/secrets/nexolab/mqtt-password
MQTT_TLS_CA_FILE=/run/secrets/nexolab/mqtt-ca.pem
```

Optional mutual-TLS client identity:

```text
MQTT_TLS_CERT_FILE=/run/secrets/nexolab/mqtt-client.pem
MQTT_TLS_KEY_FILE=/run/secrets/nexolab/mqtt-client.key
```

The certificate and key must be configured together.

### Telemetry ingestion

```text
MQTT_AUTH_REQUIRED=true
MQTT_TLS_REQUIRED=true
MQTT_HOST=<exact certificate DNS name>
MQTT_PORT=8883
MQTT_USERNAME=<ingestion username>
MQTT_PASSWORD_FILE=/run/secrets/nexolab/ingestion-password
MQTT_TLS_CA_FILE=/run/secrets/nexolab/mqtt-ca.pem
```

### Broker-control administrator

```text
NEXOLAB_MQTT_BROKER_HOST=<exact certificate DNS name>
NEXOLAB_MQTT_BROKER_PORT=8883
NEXOLAB_MQTT_TLS_REQUIRED=true
NEXOLAB_MQTT_TLS_CA_FILE=/run/secrets/nexolab/mqtt-ca.pem
NEXOLAB_MQTT_ADMIN_USERNAME=<admin username>
NEXOLAB_MQTT_ADMIN_CLIENT_ID=nexolab-broker-control-worker
NEXOLAB_MQTT_ADMIN_PASSWORD_FILE=/run/secrets/nexolab/admin-password
```

Optional administrator client certificate and key use:

```text
NEXOLAB_MQTT_TLS_CERT_FILE=/run/secrets/nexolab/admin-client.pem
NEXOLAB_MQTT_TLS_KEY_FILE=/run/secrets/nexolab/admin-client.key
```

## Deployment validation

Validate Compose interpolation before starting services:

```bash
docker compose \
  --env-file infrastructure/compose/.env.edge-secure \
  -f infrastructure/compose/compose.edge-secure.yaml \
  config --quiet
```

Validate the certificate chain and hostname from a trusted administration host:

```bash
openssl s_client \
  -connect <broker-host>:8883 \
  -servername <broker-dns-name> \
  -CAfile /path/to/ca-bundle.pem \
  -verify_return_error \
  -verify_hostname <broker-dns-name> \
  </dev/null
```

The command must report a successful verification result. Repeat with an invalid
hostname and an untrusted CA; both commands must fail.

Confirm that plaintext MQTT is unavailable:

```bash
nc -zv <broker-host> 1883
```

A successful connection to port `1883` is a release blocker.

## Controlled startup

1. Install the CA bundle, broker certificate, broker private key, node passwords,
   and optional client identities outside the repository.
2. Validate ownership, permissions, certificate dates, SAN, and chain.
3. Start PostgreSQL and apply telemetry-service migrations.
4. Start the TLS-only Mosquitto service.
5. Verify broker health through the certificate DNS name.
6. Run Dynamic Security bootstrap and ingestion provisioning over TLS.
7. Start telemetry-service and require `/health/ready` to report MQTT ready.
8. Start Device Agents and verify their local queue depth reaches zero.
9. Confirm `/nodes` shows synchronized broker state and current health evidence.

## Server-certificate rotation

For rotation under the same CA:

1. Issue a new server certificate with the same exact SAN.
2. Verify the new certificate and private key match.
3. Install both through temporary files with restrictive permissions.
4. Atomically rename the temporary files over `server.pem` and `server.key`.
5. Restart only the Mosquitto service.
6. Confirm telemetry-service and all Device Agents reconnect over TLS.
7. Verify SQLite queues drain contiguously without duplicate telemetry.
8. Retain the previous certificate and key in protected operational backup until
   the post-rotation observation window completes.

## CA rotation

Use an overlap period; do not perform a single-step CA replacement.

1. Create a trust bundle containing the old and new CA certificates.
2. Deploy that bundle to telemetry-service, broker control, and every Device Agent.
3. Verify all clients still connect.
4. Issue and install a broker certificate signed by the new CA.
5. Restart Mosquitto and verify reconnect, queue drain, and browser state.
6. Remove the old CA from the trust bundle only after every node has received the
   new bundle and the rollback window has closed.

The trust bundle contains public certificates only. Never distribute either CA
private key.

## Credential rotation interaction

MQTT password rotation remains independent from TLS certificate rotation:

1. request credential rotation through Node Registry;
2. wait for broker-control reconciliation to become `applied`;
3. atomically replace the mounted node password file;
4. restart the affected Device Agent only;
5. verify the old password is rejected;
6. verify the unaffected node continues publishing;
7. verify the rotated node drains its durable SQLite outbox in contiguous order.

## Diagnostics

### `certificate verify failed`

Check:

- the mounted CA file is the expected trust bundle;
- the CA has `CA:TRUE` and `keyCertSign`;
- the server certificate has `serverAuth`;
- the server certificate is within its validity period;
- the full issuing chain is present.

### `hostname mismatch`

Compare `MQTT_HOST` with the certificate SAN. Do not use an IP address when the
certificate contains only a DNS SAN. Reissue the certificate or correct DNS and
runtime configuration; never disable hostname verification.

### Broker healthy but client not ready

Inspect:

- Device Agent or telemetry-service MQTT error state;
- mounted file readability inside the container;
- exact broker port;
- username/client-ID Dynamic Security assignment;
- broker ACL and reconciliation state;
- local queue depth and last acknowledged sequence.

### Broker-control retrying

Run the administrator command with the same mounted CA and exact hostname. Any
TLS, certificate, verification, refused-connection, or explicit error diagnostic
is treated as command failure even when the underlying CLI exits with code zero.

### Sequence gap or queue not draining

Do not delete the SQLite volume. Check that queued records remain present until a
QoS 1 acknowledgement is confirmed. A successful local `publish()` return is not
sufficient evidence of delivery.

## Rollback

Rollback must preserve encrypted transport:

1. stop the affected client or broker service;
2. restore the previous verified CA bundle, certificate, key, image, or
   configuration;
3. retain PostgreSQL and Device Agent SQLite named volumes;
4. restart the minimum affected service set;
5. verify chain, hostname, TLS listener, queue drain, and contiguous sequences;
6. document the rollback in the operational audit trail.

Forbidden rollback actions:

- opening listener `1883`;
- setting an insecure TLS flag;
- disabling hostname verification;
- copying a private key into an environment variable or repository file;
- deleting SQLite or PostgreSQL volumes to clear an operational error.

## Automated release gate

`MQTT TLS Fleet Acceptance` generates an ephemeral standards-compliant CA and
server certificate, then verifies:

- trusted CA success;
- untrusted CA rejection;
- hostname mismatch rejection;
- plaintext listener unavailability;
- Device Agent, ingestion, and broker-control TLS connectivity;
- broker outage and container restart recovery;
- durable FIFO replay with contiguous independent sequences;
- one-node password rotation and unaffected-node continuity;
- browser-visible online and synchronized state;
- absence of private keys from uploaded evidence.

## Deferred physical gate

The following require access to the laboratory hosts and remain intentionally
deferred:

- installation of the laboratory CA on Raspberry Pi nodes;
- stable production DNS and LAN hostname validation;
- physical Ethernet outage and switch recovery;
- central-host certificate renewal automation;
- multi-hour physical backlog replay;
- certificate rotation during real RS-485 acquisition.
