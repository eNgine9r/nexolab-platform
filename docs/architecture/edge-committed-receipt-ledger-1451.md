# NEXOLAB Issue #1451 — Edge durable committed receipt ledger (source-only)

**Scope status:** isolated library and SQLite regression tests only. Production `DeviceAgent` remains on its existing `OfflineQueue`, deleting records after MQTT QoS1 PUBACK. The new `CommittedReceiptQueue` is NOT instantiated by production, has no MQTT receipt subscription, no activation flag, and does not claim end-to-end durability.

## SQLite contract

`receipt_retention.CommittedReceiptQueue` inherits the existing SQLite telemetry sequence storage and adds `apply_committed_receipt`. Only the oldest pending **organization/node telemetry** row may be pruned, after pure v1 protocol validation and a separately supplied verified central publisher authorization decision. Validation, insertion of a receipt replay ID and conditional deletion of exactly one queued event run inside a single `BEGIN IMMEDIATE` transaction using the existing bounded SQLite-busy retry machinery. `durably_spooled` is informational and persists an ID without deletion. Duplicate, wrong-node, wrong-tenant, wrong-event, stale, out-of-order, or unauthorized ACKs never prune.

`services/device-agent/durable_receipt_v1.py` is byte-identical to the canonical `contracts/durable_receipt_v1.py`, because the current Device Agent isolated Docker build context copies only `*.py` from its own directory. A test fails closed on any source drift. This is a temporary packaging limitation; future production wiring should extract a versioned shared artifact rather than silently diverging protocol copies.

## Boundaries and next acceptance

Source-only SQL and hermetic tests do not prove broker identity, real Central PostgreSQL commitment, subscription behavior, bounded replay under MQTT outages, finite disk capacity, ARM64 system service health or protected Pi recovery. No live credentials, ACLs, hardware, Modbus write, deployment, or database migration were applied. The production retention-mode switch and subscriber require separate integrated acceptance of Issue #1445 central publisher, Issue #1449 broker ACL and owner-approved protected backup/restore #1428 and network #1399. Do not mark hardware/site acceptance GREEN without field evidence.

## Local integrity and bounded contention

The staged ledger refuses a receipt when the **existing** SQLite outbox row's `event_id` column disagrees with its serialized `event_id`, or the serialized node, optional organization or optional stream identity disagrees with trusted local configuration. Duplicate JSON keys in a local queued payload are rejected. An unauthorized, corrupted, malformed, future-dated, replayed or out-of-order receipt never removes a row. A bounded SQLite `BEGIN IMMEDIATE` lock timeout and retry exhaustion preserve the original pending event; a later retry succeeds after the lock is released. These checks are isolated synthetic SQLite tests, not real Edge offline acceptance.
