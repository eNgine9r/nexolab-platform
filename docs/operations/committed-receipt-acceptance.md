# Committed-receipt end-to-end acceptance (#1762 slices 3-4)

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

| Phase                   | What happens                                                                                                                                                                                                                                 | Assertion                                                                                                                                                                                                                                         |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. Steady flow          | 4 rows/s (simulator)                                                                                                                                                                                                                         | Receipts are applied; the Edge outbox stays bounded.                                                                                                                                                                                              |
| 2. Central outage       | `telemetry-service` stopped; Device Agent recreated with a 0.04 s sample interval until at least 1,200 rows are pending                                                                                                                      | Broker logs `Outgoing messages are being dropped for client nexolab-central-ingestion`.                                                                                                                                                           |
| 3. Invalid receipts     | Valid-looking receipt for a pending row that is not in PostgreSQL, from another node, the Edge receipt identity and the node telemetry identity; then wrong-node, wrong-sequence, unknown-row and duplicate receipts from the real publisher | Forged receipts are not delivered (ACL). The others are rejected (`receipt_identity_mismatch`, `receipt_sequence_mismatch`, `no_matching_pending_telemetry`, `receipt_id_already_processed`). No receipt is applied; no row is pruned.            |
| 4. Edge restart         | Device Agent recreated during the outage with a 0.25 s live interval                                                                                                                                                                         | No pending row is lost.                                                                                                                                                                                                                           |
| 5. Central restart      | `telemetry-service` started; bounded bulk catch-up while live flow continues                                                                                                                                                                 | Live rows keep being generated. Net backlog drain from readiness until half the backlog is gone is at least **50 rows/s** (throughput gate).                                                                                                      |
| 6. Edge restart         | Device Agent restarted mid-catch-up                                                                                                                                                                                                          | Pending rows and the receipt ledger survive.                                                                                                                                                                                                      |
| 7. Drain and accounting | Wait until the Edge outbox is empty                                                                                                                                                                                                          | PostgreSQL holds every sequence `1..last_sequence` exactly once, with no duplicate `event_id` or sequence. Every row pending at the outage snapshot is in PostgreSQL with its original sequence. The forged-receipt target row is committed once. |

The invalid-receipt target is the oldest pending row that is not yet in PostgreSQL. A row committed just before the outage can still be waiting for its receipt, and with exact-row binding any pending row is a valid target, so the check must use a row whose loss the accounting would detect.

The run is bounded: every wait has a timeout, the scenario step has a 15-minute limit and the job 20 minutes.

## Reading the summary

The job writes `summary.md` to the job summary page and uploads the artifact `committed-receipt-acceptance-evidence` (`summary.json`, `accounting.json`, `catch-up-samples.csv`, `timeline.log`, health snapshots, broker overflow log, service logs).

The **Measured recovery throughput** table has four rows:

- **Catch-up, net backlog drain with live flow.** From central readiness until half of the backlog present at readiness is gone. Rows are Edge pending rows removed, net of the live rows generated at the same time. This is the gated number (at least 50 rows/s). Central start-up time is reported separately and is not in the window.
- **Catch-up, PostgreSQL commits.** Rows committed in PostgreSQL in the same window (backlog and live).
- **After the mid-catch-up Edge restart.** The Device Agent sends every retained row once, then the catch-up resends what the broker dropped.
- **Whole recovery.** From central restart to an empty Edge outbox.

The summary is written before the throughput gate is enforced, so a run below the gate still shows its numbers. A correctness failure (lost row, duplicate, wrong prune, forged receipt delivered) stops the run before the summary; read `timeline.log` first, then `services.log`.

### How the catch-up works (#1762 slice 4)

- The Edge accepts a valid receipt for any pending row, but only for the exact row it names (event id, sequence, organization, node and telemetry topic). Receipts for live rows are applied at once, even while older rows are still missing.
- The Edge resends pending rows first sent more than `DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS` ago in FIFO windows: at most `DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW` (50) rows in flight and at most `DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND` (200). A window that gets no receipt at all backs off exponentially, so a long central outage is not flooded. Nothing is resent while the telemetry connection is down.
- Central wakes its receipt publisher on each ingestion commit and publishes up to `NEXOLAB_RECEIPT_PUBLISHER_BATCH_SIZE` (50) receipts per batch, each with its own QoS 1 PUBACK and durable retry lease.
- Keep the catch-up window below the broker's per-client capacity for the central ingestion consumer (`max_inflight_messages` plus `max_queued_messages`), or the broker drops resent rows again. The production broker config has 100 and 10,000.

### Measured throughput

Gate: at least 50 rows/s net. In the slice 4 runs the catch-up was limited by the central round trip (about 33 of 50 rows in flight), not by the Edge rate cap. Whole recovery includes the mid-catch-up Edge restart and its full resend. At about 64 rows/s net, the 2026-11-25 loss (about 53,000 rows) would drain in about 14 minutes on the CI runner. The Pi is not measured.

| Run                                                | Catch-up (rows/s)                                | Whole recovery (rows/s) |
| -------------------------------------------------- | ------------------------------------------------ | ----------------------- |
| Slice 3 (head replay), run 45688608839             | 1.14 (head replay)                               | 2.3                     |
| Slice 4 (bulk catch-up), run 45696227212 attempt 1 | 65.1 net (68.9 PostgreSQL commits), live flow on | 36.0                    |
| Slice 4 (bulk catch-up), run 45696227212 attempt 2 | 63.8 net, live flow on                           | 39.1                    |

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
- The Edge replay-after interval is 5 s in the fixture (default 60 s) to keep the job short. The catch-up window, rate cap, publisher batch size and idle poll use their defaults.
- The CI runner is not a Raspberry Pi. Site catch-up throughput on the Pi, with real PostgreSQL load and the site broker, is **UNVERIFIED**.
