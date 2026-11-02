# NEXOLAB Issue #1451 — Edge durable committed receipt ledger (source-only)

**Scope status:** isolated library and SQLite regression tests only. Production `DeviceAgent` remains on its existing `OfflineQueue`, deleting records after MQTT QoS1 PUBACK. The new `CommittedReceiptQueue` is NOT instantiated by production, has no MQTT receipt subscription, no activation flag, and does not claim end-to-end durability.

## SQLite contract

`receipt_retention.CommittedReceiptQueue` inherits the existing SQLite telemetry sequence storage and adds `apply_committed_receipt`. Only the oldest pending **organization/node telemetry** row may be pruned, after pure v1 protocol validation and a separately supplied verified central publisher authorization decision. Validation, insertion of a receipt replay ID and conditional deletion of exactly one queued event run inside a single `BEGIN IMMEDIATE` transaction using the existing bounded SQLite-busy retry machinery. `durably_spooled` is informational and persists an ID without deletion. Duplicate, wrong-node, wrong-tenant, wrong-event, stale, out-of-order, or unauthorized ACKs never prune.

`services/device-agent/durable_receipt_v1.py` is byte-identical to the canonical `contracts/durable_receipt_v1.py`, because the current Device Agent isolated Docker build context copies only `*.py` from its own directory. A test fails closed on any source drift. This is a temporary packaging limitation; future production wiring should extract a versioned shared artifact rather than silently diverging protocol copies.

## Boundaries and next acceptance

Source-only SQL and hermetic tests do not prove broker identity, real Central PostgreSQL commitment, subscription behavior, bounded replay under MQTT outages, finite disk capacity, ARM64 system service health or protected Pi recovery. No live credentials, ACLs, hardware, Modbus write, deployment, or database migration were applied. The production retention-mode switch and subscriber require separate integrated acceptance of Issue #1445 central publisher, Issue #1449 broker ACL and owner-approved protected backup/restore #1428 and network #1399. Do not mark hardware/site acceptance GREEN without field evidence.

## Local integrity and bounded contention

The staged ledger refuses a receipt when the **existing** SQLite outbox row's `event_id` column disagrees with its serialized `event_id`, or the serialized node, optional organization or optional stream identity disagrees with trusted local configuration. Duplicate JSON keys in a local queued payload are rejected. An unauthorized, corrupted, malformed, future-dated, replayed or out-of-order receipt never removes a row. A bounded SQLite `BEGIN IMMEDIATE` lock timeout and retry exhaustion preserve the original pending event; a later retry succeeds after the lock is released. These checks are isolated synthetic SQLite tests, not real Edge offline acceptance.

## Guard against accidental legacy PUBACK pruning

`CommittedReceiptQueue.delete()` deliberately **rejects every direct deletion** with `postgres_committed_receipt_required`. This blocks the inherited MQTT QoS1 PUBACK deletion path if someone accidentally swaps the queue type without implementing authenticated receipt replay. The only permitted prune is the final receipt's strictly validated atomic SQLite transaction. It is still **not safe to instantiate this candidate inside the existing production `DeviceAgent`**: its unchanged `flush_queue()` would fail closed on the explicit guard. A complete opt-in runtime implementation must separately provide bounded publish attempts, replay/backpressure, broker identity proof and explicit rollback testing before activation.

## 2026-11-01 — Bounded FIFO replay and capacity observation (still source-only)

`receipt_replay.CommittedReceiptReplay` is a new **unwired** library that
publishes at most the oldest pending org-scoped telemetry event per call, using
the original durable event ID and node sequence. A callback must return exactly
`True` only after MQTT QoS1 broker PUBACK. Any broker PUBACK leaves the
SQLite row untouched until separately authenticated `postgres_committed`
receipt validation. Every attempt, including an acknowledged publish, is
throttled by bounded exponential backoff (default 5–300 s); even repeated
calls cannot flood a stalled subscriber. Legacy/unscoped or cross-tenant
oldest rows block replay without skipping FIFO order. Malformed or corrupted
queued payloads fail closed before network calls.

`CommittedReceiptQueue.oldest_receipt_replay_candidate` reads the original
SQLite event ID, topic and JSON payload without mutation.
`CommittedReceiptQueue.replay_capacity_snapshot` reports queue depth,
UTF-8 payload bytes, SQLite file bytes, free filesystem bytes, and age of the
oldest pending record. Invalid timestamps remain unknown, never zero;
these indicators do **not** prove retention guarantees or independent backups.

This stage has no integration with the production `DeviceAgent`, no
MQTT subscriber or installed broker-authentication proof, no default-on
mode, and no site activation. Source-only regression includes original event
preservation, FIFO after actual committed receipt, PUBACK without prune,
informational ACK, restart, invalid sequence, duplicate keys, wrong node,
unscoped and wrong tenant, bounded retry and disk-capacity observation.
On Raspberry Pi ARM64 in an isolated Python virtualenv with existing
pinned requirements: 357/357 Device Agent module tests and 23/23 v1
receipt contract tests passed. This is software-only, not real broker,
network outage, disk-full, power-loss or hardware acceptance.

Release remains blocked by #1445 central producer, #1449 verified broker
ACL, #1447 residual security decision, #1428 complete site backup/restore
and #1399 guarded network recovery. Full CI on this branch may fail until
the independent security exception repair lands; never bypass it.

## 2026-11-02 — Enforce global FIFO at committed receipt acceptance

The first isolated implementation searched for the oldest row **matching the
scoped telemetry topic** while its replay counterpart refused to skip an older
legacy, foreign-tenant or health row. This mismatch could accept a final
PostgreSQL receipt and prune a later event despite an earlier, unreplayable
outbox record. The receipt transaction now reads the **globally** oldest row,
rejects `oldest_pending_topic_not_scoped` when the topic does not equal the
trusted canonical telemetry topic, and leaves all queued rows and the receipt
ledger unchanged. The exact FIFO guard applies to both final
`postgres_committed` and informational `durably_spooled` receipts.

Synthetic fixtures cover legacy `nexolab/telemetry`, wrong-organization
`nexolab/v1/.../telemetry`, foreign `health` stream, no accidental ledger
insert, and successful scoped receipt only after fixture-local resolution of
the blocking older row. The repair is source-only; the fixture's direct
SQLite cleanup is never part of the production code. No installed
subscriber, broker ACL identity, central PG commitment, offline site or
hardware acceptance is implied.

## 2026-11-02 — Synthetic actual SQLite_FULL rollback

A focused regression bounds a _temporary_ SQLite fixture to its existing page
count using `PRAGMA max_page_count`; attempting a final committed receipt
raises real `sqlite3.OperationalError: database or disk is full`. Its oldest
telemetry event and failed receipt ledger remain untouched, the SQLite
transaction ends cleanly, and clearing only the fixture-local limit permits
the identical receipt to commit atomically. This demonstrates transactional
failure and recovery under a bounded synthetic page ceiling, not actual site
SSD endurance, full-disk stress, battery-backed power-loss testing or disaster
recovery. No production database is accessed.

## 2026-11-02 — Independent Python-process SQLite replay proof

An isolated test first persists one telemetry event with its exact
`event_id` and `node_sequence`, receives a synthetic QoS1 PUBACK and
intentionally leaves the row queued. It closes the original SQLite connection,
launches a **separate Python OS process** with the same temporary SQLite file
and checks the new process resends the original payload and still retains the
row after its second PUBACK. Only a synthetic separately authorized
`postgres_committed` v1 receipt in the reopened test fixture atomically
prunes the row. A final SQLite reopen sees an empty queue.

This demonstrates application-process restart persistence, not a physical
Raspberry reboot, actual MQTT broker, site ACL identity, central PostgreSQL
transaction, disk power-loss durability, network partition or hardware
acceptance. Live `DeviceAgent` remains unwired.
