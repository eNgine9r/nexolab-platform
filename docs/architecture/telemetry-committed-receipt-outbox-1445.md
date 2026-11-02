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

## 2026-11-02 — Isolated real Mosquitto + actual PG commit → Edge SQLite proof

An additional, bounded cross-component acceptance ran on `nexolab-edge-01`
in a private, non-installed **PostgreSQL 17.11** cluster and a separately
extracted **Mosquitto 2.0.21** broker. PostgreSQL used an owner-only Unix
socket, no TCP listener; Mosquitto listened only on
`127.0.0.1:18884` (the live broker remains on `127.0.0.1:1883`).
No system-wide package install, Docker/IPAM change or live MQTT/PG access.

The synthetic broker required passwords and had separate static ACLs:
`fixture-central` could publish only to
`nexolab/v1/+/+/receipts`; `fixture-edge` could read only
`nexolab/v1/00000000-0000-0000-0000-000000000001/receipt-edge-01/receipts`.
The credentials and test database lived only in restricted engineering
fixture directories, outside the repository.

Verified black-box behavior:

1. Real central `CommittedReceiptMqttSender` published a valid v1 receipt
   through Paho MQTT 3.1.1 using non-retained QoS1, obtained actual broker
   PUBACK, and an independent authenticated subscriber received the exact
   bytes. Edge's temporary SQLite outbox was **not** pruned on PUBACK;
   the source-only final-receipt consumer pruned the correct pending event
   only after applying the received payload. A new SQLite connection verified
   the durable result.
2. Real Mosquitto did **not** deliver a valid receipt for a different tenant
   to a subscriber restricted to its own tenant, even when an MQTT 3.1.1
   `SUBACK` appeared successful. Therefore tests must assert **delivery or
   non-delivery**, not infer ACL authorization from SUBACK alone.
3. A node-client attempt to publish a forged receipt to its own topic was
   **not delivered** to the subscribed node.
4. An independently verified actual PostgreSQL telemetry+receipt-intent
   commit flowed through `CommittedReceiptPublisher.run_once`, the actual
   QoS1 Mosquitto transport, exact-topic Edge subscriber, and source-only
   SQLite receipt-ledger prune; all steps **PASS**. This used synthetic node
   and tenant identities and an explicitly trusted synthetic ACL fixture.

Reproducibility fingerprints of the executed fixture scripts retained in
the _private engineering workspace_ (not production or committed scripts):

- MQTT ACL/delivery fixture SHA256
  `472565e4e780e9f6c28824a64b212996c65897f5fb20cececc295a700db61ec8`.
- PostgreSQL → MQTT → Edge proof SHA256
  `c4fa9312704f58ed8f01bce9c116e13b3abb00831349cc69bc04ca1f28828e77`.

Both engineering services were explicitly stopped after the tests;
`nexolab-central-postgres-1` remained **healthy**, and the installed broker
continued listening at its existing loopback port. This is **not** validation
of the installed Mosquitto Dynamic Security ACL, TLS/site identity,
PostgreSQL 16 in the real live topology, production `DeviceAgent` wiring,
actual energy-meter values, physical hardware or outage/reboot recovery.
The test explicitly passes `central_publisher_authorized=True` because
the _synthetic_ ACL origin was independently controlled and verified;
no production authentication verdict can be inferred from that boolean.

## 2026-11-02 — Persistent CI regression for PostgreSQL receipt/Edge protocol parity

`tests/test_committed_receipt_outbox.py` now exercises an actual transactional
PostgreSQL commit and the staged central receipt publisher. Its synthetic
broker callback independently validates the bytes against the canonical
`contracts/durable_receipt_v1.py::validate_for_pending` used by Edge. The
test checks that the committed PostgreSQL receipt intent exists before any
publish, that sender preflight accepts the exact canonical topic and payload,
and that a synthetic broker ACK marks the durable intent published only after
the callback validates the message. Because this is a permanently checked-in
test within the existing Telemetry service suite, GitHub's PostgreSQL 16
workflow will exercise this contract for future revisions.

Stand-alone PostgreSQL test fixtures explicitly load the SQLAlchemy model
registry before creating schema, removing a dependency on unrelated test
module import ordering. On a _separate, synthetic PostgreSQL 17.11_ database
and a Raspberry ARM64 engineering checkout this expanded suite passed
**38/38 tests, zero skips**. This is an independently reproduced local
PostgreSQL result, not yet evidence of exact-head GitHub CI or an installed
site PostgreSQL 16 runtime. `central_publisher_authorized=True` and the
PUBACK callback are **synthetic-only**. The test never calls production MQTT,
a physical controller, site PostgreSQL or the real Edge subscriber.
