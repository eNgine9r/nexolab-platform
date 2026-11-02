# #1445 — Central committed receipt outbox (development checkpoint)

**Scope:** source-only transactional outbox foundation for `postgres_committed` receipt intents. **This is NOT an installed publisher or end-to-end durability guarantee.**

Current code adds opt-in `Database.persist(..., receipt_identity=...)` and an additive table/migration. There are **no production callers providing receipt_identity**, no receipt MQTT publisher, no broker identity/ACL proof, no Edge receipt subscription, no Edge SQLite deletion changes, and no site migration executed. Existing behavior is unchanged by default.

## Exact safety boundary

- A trusted caller MUST first establish broker-enforced node publisher authentication/ACL, and execute `NodeIngressAuthorizer.authorize` successfully for a node-scoped telemetry topic; `CommittedReceiptIdentity` is **not** authority in itself.
- The `organization_id` is from the authenticated, authorized node topic, never claimed solely from message JSON; sequence is matched to the validated raw envelope. No unscoped legacy receipt.
- The optional outbox insertion is within the same SQLAlchemy transaction as telemetry insert and latest projection. Duplicate event ID must have byte-equivalent decoded JSON plus matching node/tenant/sequence; mismatches fail closed.
- Receipt is a **queued intent**, not emitted to MQTT here. Publisher must later separately prove actual PostgreSQL commit before sending, durable pending retries, broker ACL, local auth and restart behavior.
- Outbox capacity is bounded; failure aborts the entire transaction so no sample commit exists without a corresponding intent for opt-in events.
- The committed-intent transaction tests now require PostgreSQL and skip without a real PostgreSQL test database. A separate SQLite test asserts the engine rejects any attempt to claim a PostgreSQL commit. Database migration/operational MQTT/site acceptance remains separate, and the PostgreSQL advisory lock in the opt-in path serializes capacity checks.

## Outstanding acceptance for #1445

1. Independently verified trusted node topic/sequence derivation at actual ingress and opt-in setting; reject legacy/unscoped/forged sources.
2. Bounded crash-safe receipt publisher with persisted retry, MQTT QoS 1 ACK, central identity / broker ACL gate and deterministic tests.
3. Live Postgres transaction/migration integration tests, broker outage and idempotent duplicate tests, full exact-head CI and review.
4. Canonical Sprint/checkpoint reconciliation, no site cutover without full protected backup + restore, rollback evidence and owner approval.

No hardware writes, secrets or production volumes are touched.

## Current sender-core increment

`app/committed_receipt_publisher.py` provides a **not-runtime-wired** bounded
one-attempt publisher with PostgreSQL row locking, durable retry lease, exponential
backoff, duplicate-after-PUBACK reissue and pending age/count diagnostics.
Its injected `sender` returns true only for a broker PUBACK according to the
caller's contract. Neither this interface nor any mock test proves a broker
principal, installed ACL, actual Edge receipt delivery or lossless behavior.

Publisher construction refuses SQLite. Receipt intent construction refuses
SQLite. Integration tests require a real PostgreSQL test database. Pending
broker/identity/real-MQTT tests and runtime wiring remain **unfinished**.

### Per-node publish ordering

CommittedReceiptPublisher source-only scheduler excludes a newer pending sequence when any earlier sequence for the same organization/node is still unpublished, even if its retry lease is backed off or another worker holds the earlier row. Other nodes can publish independently. This prevents a known older receipt from being overtaken, **but cannot prove whether a yet-uncommitted earlier sample exists**. Broker PUBACK does not prove Edge acceptance: subscriber-side pending FIFO, durable replay requests, ACL acceptance and isolated outages remain separate gates.

## 2026-11-02 — Fail-closed MQTT transport receipt schema (source-only)

The staged dedicated QoS1 sender must not treat broker PUBACK as a successful
receipt when the emitted body could be rejected by the Edge v1 validator.
Before publication it rejects JSON duplicate keys (including nested
duplicates), non-canonical node identities, timestamps without time zones,
unparseable timestamps, timestamps older than seven days or more than five
minutes ahead of the local trusted clock, oversized timestamp strings, and
other topic/identity mismatches. Retained bytes must match the original event
record and exact trusted receipt topic; only PostgreSQL-backed intent may
call the transport after separately verified broker publisher ACL. A sender
callback returning True is never proof of Edge delivery.

The test fixture uses a current UTC acceptance timestamp so its positive
test does not expire with calendar time. Its standalone SQLite refusal test
now explicitly registers the documented SQLAlchemy models rather than relying
on unrelated test import order. On an isolated Raspberry Python environment,
20 focused tests passed and 17 tests requiring an independent PostgreSQL
database were skipped. These SKIPs are **not** PostgreSQL integration
acceptance; the installed site DB was not accessed, and the source remains
unwired to production.

## 2026-11-02 — Real isolated ARM64 PostgreSQL test and Edge contract handoff

To avoid running database integration tests against site PostgreSQL 16, an
engineer-owned PostgreSQL **17.11** binary was extracted into a private
worktree-adjacent fixture on `nexolab-edge-01`. The cluster listened on
**Unix socket only**, `listen_addresses=''` (no TCP); database
`nexolab_1445_fixture` contained only synthetic records. No system package,
site PostgreSQL container, production database, broker identity or network
configuration was changed.

The standalone PostgreSQL connector's SQL_ASCII default initially exposed
server metadata as bytes; setting `PGCLIENTENCODING=UTF8` for the fixture
corrected test connectivity without changing application code. The focused
suite `test_committed_receipt_outbox.py` plus
`test_committed_receipt_mqtt.py` then completed **37/37 PASS** (zero skip)
against actual PostgreSQL 17.11 on ARM64, covering transactional intent,
rollbacks, retry, duplicate commit, sequence isolation, and MQTT sender
validation. A separate synthetic end-to-end contract probe persisted an
actual PostgreSQL telemetry+receipt intent and replayed its canonical payload
through `contracts/durable_receipt_v1.py::validate_for_pending` after an
explicitly simulated broker PUBACK; this probe also **PASS**. The simulated
PUBACK and `central_publisher_authorized=True` fixture are **not real
broker-ACL authentication**, Edge delivery or hardware acceptance.

Production uses PostgreSQL **16**, not 17: this result is meaningful
PostgreSQL transactional evidence but **does not verify the exact production
server version** or site migration/restore. Physical Edge/server outage,
power-loss recovery, real broker authorization and protected backups remain
hard acceptance gates. The test fixture will be shut down without touching
site services.
