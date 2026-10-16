# NEXOLAB — Durable central telemetry receipt v1 (#1410)

**Status: design-and-validator contract ONLY.** There is no installed
producer, MQTT receipt subscriber, Edge SQLite retention change, central
PostgreSQL ACK publisher, or automatic replay enabled by this Work Package.
The currently deployed Raspberry Pi retains the original PUBACK-based
queue deletion behavior. This design does **not** establish zero data loss.

## Why a new receipt is required

The Device Agent currently stores telemetry in Edge SQLite and deletes it
after MQTT QoS 1 PUBACK. This proves broker acknowledgement, not durable
central persistence. When an offline central subscriber exceeds the
broker's finite persistent-session queue, messages can be lost before
central PostgreSQL receives them. The isolated test in #1394 demonstrated
this class with a deliberately small cap (10) and 15 publishes, NOT a
measured production loss. The main follow-up requirement is #1397.

## Message envelope and topic

Protocol: JSON UTF-8 bytes, max 2048 bytes, JSON Schema Draft 2020-12 at
`contracts/telemetry-durable-receipt.v1.schema.json`, version 1.
Only node-scoped **organization-authenticated** telemetry is eligible.

Topic:

```text
nexolab/v1/{organization_id}/{node_id}/receipts
```

Example message:

```json
{
  "contract_version": 1,
  "receipt_id": "a21f4e73-83b6-4ead-86c5-f8ba5c7fb6e1",
  "event_id": "a1f59453-86e3-43f7-b093-c814b20d5cc5",
  "organization_id": "28dceec5-3a75-4d03-b5ec-b21122b35778",
  "node_id": "edge-01",
  "stream": "telemetry",
  "node_sequence": 41,
  "receipt_level": "postgres_committed",
  "accepted_at": "2026-10-16T12:01:02Z"
}
```

`event_id` and `node_sequence` are immutable original event identities.
The central service must never invent a replacement identity for a
duplicate event. Each `receipt_id` identifies a reply, not a new
measurement. Receipt timestamps are evidence metadata, never proof of
database commitment by themselves.

## Semantics and deletion safety

- `durably_spooled` is an **informational** receipt: central has
  durably staged the event according to separately verified spool/fsync
  conditions, but the Edge MUST NOT delete it from SQLite under this
  default v1 acceptance policy.
- `postgres_committed` may authorize deleting exactly one matching
  Edge SQLite outbox row, but only after a central transaction is
  actually committed, the receipt is validated from an authenticated
  origin and the corresponding event is still pending in SQLite.
- The validator checks the _trusted local_ pending event ID, tenant,
  node ID, stream, sequence and exact MQTT receipt topic. For a
  committed receipt, the event's sequence must be the **oldest**
  pending telemetry sequence. A later event's ACK cannot conceal
  missing earlier data. Use a single atomic SQLite transaction when
  the Edge eventually performs receipt validation and deletion.
- Invalid, duplicate, unexpected, cross-tenant, stale or unscoped
  receipts must never delete queued data. Receipt ID replay protection,
  queue/sequence revalidation and transaction boundaries belong in
  the later Edge receiver implementation; do not misrepresent the
  stateless protocol validator as complete replay protection.
- No policy change from `postgres_committed` to
  `durably_spooled` deletion is permitted without an explicit reviewed
  product decision and documented durability/restore budget.

## Trust boundary — must be implemented BEFORE activation

**Receipt contents and MQTT topics are not signatures.** The existing
broker's current ACL/authentication state must first be verified on
the installed LOCAL_LAN deployment. The future central publisher
and Edge subscriber must use broker-enforced, appropriately isolated
identities/ACLs that prove only the accepted central service can
publish to the target node-scoped `receipts` topic. A subscriber
cannot infer publisher identity merely from JSON fields.

The pure function `contracts/durable_receipt_v1.py` defaults to
`central_publisher_authorized=False`. Future integration may set it
to true **only after** independent transport/ACL authorization evidence.
The expected tenant/node/event identity must come from trusted local
configuration and a real pending SQLite row, never from the receipt
payload. Legacy `nexolab/telemetry` unscoped streams are intentionally
not accepted without a separately reviewed migration plan.

## Subsequent independent Work Packages

1. Central-only persistent receipt publication after transaction
   commit, duplicate event handling, broker ACL authorization and
   bounded retry/spool resource accounting.
2. Edge-only subscriber, receipt match, monotonic FIFO replay and
   SQLite atomic prune with restart, forged/replayed/duplicate ACK
   and backlog-capacity tests.
3. Combined offline ARM64/Mosquitto/PostgreSQL/SQLite acceptance across
   broker cap, API stop/restart, PostgreSQL outage, crash and bounded
   disk-full scenarios. Only this can substantiate a documented
   no-loss claim within explicitly proven retention/capacity limits.

These future stages must not change acquisition cadence, write Modbus,
add mandatory cloud/API/CDN dependencies or silently erase history gaps.
