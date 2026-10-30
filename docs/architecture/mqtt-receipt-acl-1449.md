# NEXOLAB #1449 — isolated MQTT receipt ACL acceptance

**Status:** source-only Draft. No production broker, credentials, runtime, data or hardware were changed.

## Authorization

- Existing node telemetry/health/status and central ingestion grants remain unchanged.
- Opt-in `create-receipt-publisher` provisions a separate non-admin, non-node, non-ingestion principal with only `publishClientSend` on `nexolab/v1/+/+/receipts`.
- Opt-in `grant-node-receipts` requires an already provisioned exact organization/node identity and its unchanged telemetry role; assigns `subscribeLiteral`, `unsubscribeLiteral`, and `publishClientReceive` for the precise node receipt topic. Literal matching excludes wildcard subscriptions.
- All four broker default ACL decisions must be deny. Existing role ACLs, client memberships, group membership and client-id binding are verified before changes and unknown states fail closed. Repeated provisioning must be idempotent.
- The Mosquitto CLI may omit `Disabled: false` for enabled clients; explicitly disabled clients are refused, while exact role and group checks are enforced.

## Evidence and stop conditions

The `MQTT Broker Security Acceptance` workflow runs disposable Docker Mosquitto with synthetic credentials, tests correct-node QoS1 delivery, rejects node/ingestion publishing and foreign topic subscription, verifies idempotence, collision/injection rejection, and ACL persistence after isolated broker restart. These are not installed ARM64 broker or Edge SQLite acceptance.

MQTT PUBACK does not establish Edge consumption or end-to-end data preservation. Protected site changes require separate owner authorization, full encrypted backup and isolated restore (#1428), site networking safety (#1399), completed central receipt publisher (#1445), the future Edge subscriber, and actual hardware acceptance.

## Broker-level negative evidence

Mosquitto MQTT QoS 1 publish return codes alone are not an ACL guarantee. The isolated acceptance verifies denied node and ingestion receipt PUBLISH attempts create no observable message or retained state for an authorized subscriber. It also publishes retained canary probes on foreign node/organization receipt topics and verifies those are not delivered to the wrong node. These canaries exist only in the disposable test broker; normal central receipt publication is non-retained.

## Credential and client-ID protection

Dedicated receipt publisher user and client IDs must both use the `nexolab-central-receipts-` namespace, preventing accidentally reusing any existing node or ingestion MQTT client ID. The opt-in command requires a non-symlink regular secret file with `0400` or `0600` mode before role reconciliation. Isolated broker regression refuses a node client ID collision and a world-readable synthetic secret. These rules do not rotate or change production credentials.
