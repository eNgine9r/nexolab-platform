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
