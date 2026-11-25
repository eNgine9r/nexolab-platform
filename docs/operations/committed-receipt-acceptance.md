# Committed-receipt end-to-end acceptance (#1762 slice 3)

This runbook covers the isolated GitHub Actions acceptance for the committed-receipt chain, how to read its summary, and how the owner provisions the two dedicated receipt identities.

The acceptance is a disposable CI fixture. It does not change a site, a production broker, a production database or hardware. Both runtime flags stay `disabled` by default everywhere. Site activation still needs #1428, an approved release and owner-provisioned identities.

## What runs

Workflow **Committed Receipt Acceptance** (`.github/workflows/committed-receipt-acceptance.yml`), job **Committed-receipt end-to-end acceptance**, script `scripts/run-committed-receipt-acceptance.sh`.

It starts the existing broker-control acceptance stack (`infrastructure/compose/compose.broker-control-acceptance.yaml`) with the overlay `infrastructure/compose/compose.committed-receipt-acceptance.yaml`:

- Mosquitto with Dynamic Security, default deny, and the production broker config with one change: `max_queued_messages 10`;
- PostgreSQL 16 and the telemetry-service with `NEXOLAB_COMMITTED_RECEIPTS=enabled` and the dedicated publisher identity;
- one Device Agent with `DEVICE_AGENT_COMMITTED_RECEIPTS=enabled`, the dedicated Edge receipt identity and `DEVICE_MODE=simulator` (no Modbus, no serial device).

All credentials are generated at runtime and deleted on exit. The two receipt identities are created with the same admin commands the owner uses on site (see below). The node telemetry identity is provisioned through the API and broker control, as in the fleet acceptance.

Topology: the Device Agent connects directly to the central broker, as in `compose.edge-secure.yaml`. The queue that overflows is the broker's persistent-session queue for the offline central ingestion consumer. The broker sends PUBACK to the Device Agent and then drops the message, which is the same drop-after-PUBACK mechanism as the Edge bridge queue cap in the 2026-11-25 incident.

## Scenario and assertions

| Phase                   | What happens                                                                                                                                                                                            | Assertion                                                                                                                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Steady flow          | 4 rows/s (simulator)                                                                                                                                                                                    | Receipts are applied; the Edge outbox stays bounded.                                                                                                                                                                                            |
| 2. Central outage       | `telemetry-service` stopped until at least 200 rows are pending                                                                                                                                         | Broker logs `Outgoing messages are being dropped for client nexolab-central-ingestion`.                                                                                                                                                         |
| 3. Invalid receipts     | Valid-looking receipt for the head row from another node, the Edge receipt identity and the node telemetry identity; then a wrong-node, an out-of-order and a duplicate receipt from the real publisher | Forged receipts are not delivered (ACL). The others are rejected (`receipt_identity_mismatch`, `receipt_id_already_processed`). No receipt is applied; the head row stays.                                                                      |
| 4. Edge restart         | Device Agent recreated during the outage (live interval 10 s)                                                                                                                                           | No pending row is lost.                                                                                                                                                                                                                         |
| 5. Central restart      | `telemetry-service` started                                                                                                                                                                             | Head replay commits rows one by one.                                                                                                                                                                                                            |
| 6. Edge restart         | Device Agent restarted mid-replay                                                                                                                                                                       | Pending rows and the receipt ledger survive.                                                                                                                                                                                                    |
| 7. Drain and accounting | Wait until the Edge outbox is empty                                                                                                                                                                     | PostgreSQL holds every sequence `1..last_sequence` exactly once, with no duplicate `event_id` or sequence. Every row pending at the outage snapshot is in PostgreSQL with its original sequence. The forged-receipt head row is committed once. |

The run is bounded: every wait has a timeout, the scenario step has a 15-minute limit and the job 20 minutes.

## Reading the summary

The job writes `summary.md` to the job summary page and uploads the artifact `committed-receipt-acceptance-evidence` (`summary.json`, `accounting.json`, `timeline.log`, health snapshots, broker overflow log, service logs).

The **Measured recovery throughput** table has three rows:

- **Head replay after central restart.** Rows committed per second while the Edge replays only its oldest row and waits for its receipt. This is the rate of the replay design: one row per receipt round trip, bounded by the Edge replay interval (0.2 s) and the central publisher idle poll (1.0 s).
- **After the mid-replay Edge restart.** After a restart the Device Agent sends every retained row once. Central deduplicates by `event_id` and returns receipts in sequence order, so this phase is much faster.
- **Whole recovery.** From central restart to an empty Edge outbox.

The summary also extrapolates the head-replay rate to the 2026-11-25 loss (about 53,000 rows) and says whether head replay converges while the site keeps producing about 4.5 rows/s.

A FAIL summary means a correctness assertion failed. Read `timeline.log` first, then `services.log`.

## Owner provisioning of the two receipt identities

Run these on the broker host with the packaged admin tool. Use TLS for any non-loopback broker; the tool refuses plaintext remote administration. Each password file must be a regular file with mode `0400` or `0600`. Never paste a secret on the command line.

Central receipt publisher, publish-only on `nexolab/v1/{org}/+/receipts`:

```sh
nexolab-dynsec-admin create-org-receipt-publisher \
  nexolab-central-receipts-<name> nexolab-central-receipts-<name> \
  <organization-id> /run/secrets/nexolab/receipt-publisher-password
```

Edge receipt subscriber for one node, literal read-only on `nexolab/v1/{org}/{node}/receipts`, no publish:

```sh
nexolab-dynsec-admin create-node-receipt-subscriber \
  receipts:<organization-id>:<node-id> \
  nexolab-<organization-id>-<node-id>-receipts \
  <organization-id> <node-id> /run/secrets/nexolab/<node-id>-receipt-password
```

Rules enforced by the tool:

- both commands require all four broker default ACL decisions to be `deny`;
- the publisher username and client id must be in the `nexolab-central-receipts-*` namespace and cannot reuse the admin, ingestion, node or subscriber principals; an existing client with any other role is refused;
- the subscriber username must be exactly `receipts:{org}:{node}` and the client id exactly `nexolab-{org}-{node}-receipts`, so it can never be the node telemetry principal;
- the organization id must be a canonical lowercase UUID and the node id a safe lowercase name (no `+`, `#` or `/`);
- repeated runs are idempotent; an existing role with different ACLs, or a client with a different client id, roles or groups, is refused.

The existing commands are unchanged: `create-receipt-publisher` (all organizations) and `grant-node-receipts` (receipt topic on the node telemetry principal, for a bridge topology).

Configure the services with the matching settings:

- telemetry-service: `NEXOLAB_RECEIPT_PUBLISHER_USERNAME`, `NEXOLAB_RECEIPT_PUBLISHER_CLIENT_ID` and `NEXOLAB_RECEIPT_PUBLISHER_PASSWORD_FILE`;
- Device Agent: `DEVICE_AGENT_RECEIPT_MQTT_USERNAME`, `DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE`, `DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME` (the publisher username) and `DEVICE_AGENT_RECEIPT_BROKER_ACL=broker-enforced`.

The real-broker deny cases for both identities are in `scripts/run-mqtt-broker-security-acceptance.sh` (workflow **MQTT Broker Security Acceptance**).

## What this does not prove

- No real hardware, Modbus device, site broker, site ACL, TLS site identity or site PostgreSQL was used. Site behaviour stays **UNVERIFIED**.
- No power loss, Edge-to-central bridge, network move or clock step was simulated.
- The Edge replay-after interval is 5 s in the fixture (default 60 s) to keep the job short. The replay interval and publisher idle poll use their defaults.
