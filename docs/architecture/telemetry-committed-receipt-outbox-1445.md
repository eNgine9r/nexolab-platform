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
