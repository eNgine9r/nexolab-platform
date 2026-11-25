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

## 2026-11-25 — Runtime wiring behind a default-OFF flag (#1762 slice 1)

The central pieces are now connected to the telemetry-service runtime, but
only behind `NEXOLAB_COMMITTED_RECEIPTS`:

| Value                | Behaviour                                                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `disabled` (default) | Unchanged: separate `NodeIngressAuthorizer.authorize` then `persist(event, raw)`; no publisher thread; readiness and metrics output unchanged. |
| `enabled`            | Org-scoped node telemetry topics use `authorize_and_persist_committed` (registry, cursor, sample and receipt intent in one transaction).       |

When `enabled`, startup fails closed unless all of the following hold:

- `MQTT_ENABLED=true` and `MQTT_NODE_REGISTRY_ENFORCED=true`;
- `DATABASE_URL` is PostgreSQL;
- a dedicated receipt publisher identity:
  `NEXOLAB_RECEIPT_PUBLISHER_USERNAME` and
  `NEXOLAB_RECEIPT_PUBLISHER_PASSWORD_FILE` (a mounted file, read once at
  startup, never logged), with `NEXOLAB_RECEIPT_PUBLISHER_CLIENT_ID`
  (default `nexolab-receipt-publisher`). Username and client id must differ
  from the ingestion subscriber's `MQTT_USERNAME` and `MQTT_CLIENT_ID`.
  The publisher reuses the broker host, port and CA from the MQTT TLS
  settings but never presents the ingestion client certificate.

Runtime behaviour when enabled:

- Legacy or unscoped topics keep the legacy path. Dead-letter handling,
  duplicates, live publish and `after_persist` behave as before.
- Deterministic receipt identity conflicts (for example, the same `event_id`
  with a different payload) are dead-lettered with reason
  `committed_receipt_conflict` instead of blocking the queue head.
- If the bounded receipt outbox is full, the event is persisted on the legacy
  path without a receipt intent (counted in
  `committed_receipt_outbox_full_fallback_total`). The Edge keeps the row and
  a later replay re-queues the receipt. Telemetry is never blocked by receipts.
- A background thread (`committed-receipt-publisher`) runs
  `CommittedReceiptPublisher.run_once` one intent at a time, with bounded
  exponential backoff (`NEXOLAB_RECEIPT_PUBLISHER_RETRY_INITIAL_SECONDS`,
  `..._RETRY_MAX_SECONDS`) and a graceful stop on shutdown.
- `/metrics` and `/metrics/json` gain a `committed_receipt_*` section
  (pending, oldest pending age, attempts, PUBACK-confirmed, failures, loop
  errors, transport connected). `/health/ready` adds a separate
  `committed_receipts` object (`ready`, `degraded` or `stopped`). The
  telemetry readiness verdict and HTTP status never depend on it.

**Site activation is out of scope.** It needs the protected backup and
restore gate (#1428), an approved release, and a broker receipt identity and
ACL provisioned by the owner (#1449/#1450). Until then the flag stays
`disabled` on site. The Edge side (slice 2) and the isolated end-to-end
acceptance (slice 3) are separate PRs. Hardware and site remain
**UNVERIFIED**.

## 2026-11-25 — Edge wiring behind a default-OFF flag (#1762 slice 2)

The Edge pieces (`receipt_retention.CommittedReceiptQueue`,
`receipt_replay.CommittedReceiptReplay`, `durable_receipt_v1`) are now
connected to the Device Agent through `services/device-agent/committed_receipt_mode.py`,
but only behind `DEVICE_AGENT_COMMITTED_RECEIPTS`:

| Value                | Behaviour                                                                                                                                 |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `disabled` (default) | Unchanged: legacy `OfflineQueue`, rows are deleted after the broker QoS 1 PUBACK, no receipt client, `/health` output unchanged.          |
| `enabled`            | `CommittedReceiptQueue`: PUBACK never deletes. Only a validated `postgres_committed` receipt prunes exactly one row in one SQLite commit. |

When `enabled`, startup fails closed (`Settings.from_env`) unless all of the
following hold. Errors name only the settings, never their values:

- org-scoped telemetry: `NEXOLAB_ORGANIZATION_ID` (canonical lowercase UUID),
  an explicitly set `NEXOLAB_NODE_ID` that matches the receipt contract, and
  `MQTT_AUTH_REQUIRED=true` (telemetry identity `node:{org}:{node}`);
- a dedicated Edge receipt subscriber identity, following the existing
  mounted-file credential convention:
  `DEVICE_AGENT_RECEIPT_MQTT_USERNAME`,
  `DEVICE_AGENT_RECEIPT_MQTT_PASSWORD_FILE` (read at startup, never logged)
  and `DEVICE_AGENT_RECEIPT_MQTT_CLIENT_ID` (default
  `nexolab-{org}-{node}-receipts`). Username and client id must differ from
  the telemetry `MQTT_USERNAME` and `MQTT_CLIENT_ID`. With
  `MQTT_TLS_REQUIRED=true` the receipt client trusts the same CA but never
  presents the telemetry client certificate;
- the trusted central publisher identity,
  `DEVICE_AGENT_RECEIPT_PUBLISHER_USERNAME`, in the dedicated
  `nexolab-central-receipts-*` namespace, and the operator statement
  `DEVICE_AGENT_RECEIPT_BROKER_ACL=broker-enforced` that the installed broker
  ACL lets only that identity publish to `nexolab/v1/+/+/receipts`;
- a valid replay budget: `DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS`
  (default 60), `..._REPLAY_INITIAL_RETRY_SECONDS` (5),
  `..._REPLAY_MAX_RETRY_SECONDS` (300, at least the initial value) and
  `..._REPLAY_MIN_INTERVAL_SECONDS` (0.2).

**Trust model.** MQTT 3.1.1 does not identify the publisher of a message.
`central_publisher_authorized` is therefore derived only from that validated
configuration and from delivery on the dedicated subscriber's exact
`nexolab/v1/{org}/{node}/receipts` QoS 1 subscription. It never comes from
the receipt body or topic. The real guarantee is the installed broker ACL,
which this PR does not verify.

Runtime behaviour when enabled:

- **First send.** The normal flush publishes every queued row once per
  process lifetime, in SQLite id order, and advances an in-memory cursor on
  PUBACK. It never deletes. After a restart the cursor starts at zero, so all
  retained rows are sent once more (central deduplicates by `event_id`).
- **Receipts.** A separate Paho client (dedicated identity) subscribes to the
  exact node receipt topic. Each message goes through
  `apply_committed_receipt`: forged, wrong-tenant, wrong-node, wrong-event,
  out-of-order (until slice 4, see below), stale, future, malformed and
  duplicate receipts are rejected and counted by reason; `durably_spooled` is informational and never prunes.
  The receipt ledger is durable across restarts.
- **Replay.** A `committed-receipt-replay` thread re-publishes only the oldest
  pending row, only after it waited `REPLAY_AFTER_SECONDS` since it was sent,
  and then with the bounded exponential backoff of `CommittedReceiptReplay`.
  Ticks are at least `REPLAY_MIN_INTERVAL_SECONDS` apart, and nothing is
  replayed while the telemetry connection is down. A pruning receipt wakes the
  thread so the next head is handled without waiting. Recovery from a large
  loss is therefore one row per receipt round trip: bounded, but not fast.
- **Foreign rows.** If the oldest row is not on the node's org-scoped
  telemetry topic (for example a legacy `nexolab/telemetry` row left from
  before activation), receipts and replay stop at that row and `/health`
  becomes `degraded`. Drain the outbox with the flag disabled before enabling.
- **`/health`** gains a `committed_receipts` object: pending count, oldest
  pending age, payload/SQLite/free-disk bytes, receipts applied,
  informational and rejected (by reason), first sends, replay attempts,
  PUBACKs, failures and next retry, subscriber connection and SUBACK state.
  It has no credentials or usernames. `retention_guaranteed` is always
  `false`: free disk is reported, not reserved.

**Provisioning gap.** The #1450 `nexolab-dynsec-admin grant-node-receipts`
command grants the receipt topic to the node telemetry principal
`node:{org}:{node}`. This slice requires a separate Edge receipt identity, so
the owner must provision that identity (and its read-only ACL on the node
receipt topic) before activation. That is part of #1449, not this PR.

**Site activation is out of scope.** It needs the protected backup and
restore gate (#1428), an approved release, and the broker identities and ACL
provisioned by the owner (#1449/#1450). Until then the flag stays `disabled`
on site. The tests use fake MQTT clients and synthetic receipts with real
SQLite; they are not broker-ACL, outage or hardware evidence. The isolated
end-to-end acceptance is slice 3. Hardware and site remain **UNVERIFIED**.

## 2026-11-25 — Dedicated receipt identities and isolated end-to-end acceptance (#1762 slice 3)

**Provisioning gap closed in source.** `nexolab-dynsec-admin` has two new,
explicit commands. The #1450 commands are unchanged.

- `create-org-receipt-publisher <user> <client-id> <org> <password-file>`:
  role `nexolab-central-receipts-org-{org}` with only `publishClientSend` on
  `nexolab/v1/{org}/+/receipts`. Username and client id in the
  `nexolab-central-receipts-*` namespace.
- `create-node-receipt-subscriber receipts:{org}:{node} nexolab-{org}-{node}-receipts <org> <node> <password-file>`:
  role `nexolab-node-receipt-subscriber-{org}-{node}` with only
  `subscribeLiteral`, `unsubscribeLiteral` and `publishClientReceive` on
  `nexolab/v1/{org}/{node}/receipts`. No publish.

Both fail closed on non-default-deny brokers, plaintext remote
administration, unsafe secret files and any existing role, client id or
membership that differs. The real-broker deny cases (subscriber publish,
other node, wildcard, other organization, publisher subscribe, publisher
cross-organization and telemetry) run in **MQTT Broker Security Acceptance**.

**Isolated end-to-end acceptance.** Workflow **Committed Receipt Acceptance**
runs both flags enabled against a disposable Dynamic Security broker with
`max_queued_messages 10`, PostgreSQL 16 and one simulated Device Agent. See
`docs/operations/committed-receipt-acceptance.md`. First GREEN run
(45688608839): 202 rows pending in a 93 s outage with observed broker queue
overflow (drop after PUBACK); forged receipts from three non-publisher
identities not delivered; wrong-node, out-of-order and duplicate receipts
rejected without prune; two Edge restarts lost nothing; PostgreSQL held
sequences 1..248 exactly once.

**Measured recovery throughput (defaults: Edge replay interval 0.2 s,
central publisher idle 1.0 s).** Head replay committed 1.14 rows/s. After an
Edge restart the resend of all retained rows committed 7.2 rows/s. At
1.14 rows/s the 2026-11-25 loss (about 53,000 rows) needs about 12.9 h
without live flow, and head replay cannot catch up with the site's
4.5 rows/s. From the code (not measured here): a receipt that arrives for a
row that is not the Edge head is rejected and central does not re-send it,
so after a gap every later row also needs its own replay. This is recorded as a follow-up; activation must not
rely on head replay alone. Hardware and site remain **UNVERIFIED**.

## 2026-11-25 — Bounded bulk catch-up (#1762 slice 4)

Slice 3 measured recovery at about 1.1 rows/s (head replay) and 2.3 rows/s
overall. Slice 4 removes the three causes. Both flags stay `disabled` by
default and the legacy paths are unchanged.

**Exact-row binding replaces the FIFO-head rule.** The Edge accepts a valid
`postgres_committed` receipt for **any** pending row, but only for the one
row whose `event_id`, `node_sequence`, organization, node and exact
org-scoped telemetry topic all match. `validate_for_pending` drops the
`oldest_pending_sequence` argument and takes `pending_row_topic` (the stored
topic of the named row) instead; it rejects `pending_row_topic_not_scoped`.
`apply_committed_receipt` looks the row up by the receipt `event_id` inside
the same `BEGIN IMMEDIATE` transaction as the durable `receipt_id` ledger
insert and the single-row delete. Unknown or already pruned rows are rejected
(`no_matching_pending_telemetry`); another row's sequence is rejected
(`receipt_sequence_mismatch`). Duplicate, stale, future, forged, wrong-node,
wrong-tenant, malformed and unauthenticated receipts are rejected as before.
A legacy or foreign-tenant row is never pruned, but it no longer blocks
receipts for the node's own rows; `/health` stays `degraded` while it is
there (`head_blocked_reason=foreign_topic_row`).

**Edge windowed catch-up** (`receipt_replay.CommittedReceiptCatchUp`, used by
`CommittedReceiptRuntime.replay_tick`). Pending rows first sent more than
`DEVICE_AGENT_RECEIPT_REPLAY_AFTER_SECONDS` ago are re-published in SQLite id
order, in windows:

- at most `DEVICE_AGENT_RECEIPT_CATCHUP_WINDOW` (default 50, 1..500) resent
  rows are in flight (resent, still pending, resent less than replay-after
  ago);
- a token bucket caps the resend rate at
  `DEVICE_AGENT_RECEIPT_CATCHUP_MAX_ROWS_PER_SECOND` (default 200, at most
  1000);
- one sweep walks the outbox once; the next sweep starts only replay-after
  seconds after the last window, so a row is never resent more often;
- a window that expires without a single receipt (central down) and a
  publish failure back off exponentially (`..._REPLAY_INITIAL_RETRY_SECONDS`
  to `..._REPLAY_MAX_RETRY_SECONDS`); any applied receipt ends a stall
  backoff;
- nothing is resent while the telemetry connection is down; corrupt local
  rows are skipped (never resent, never pruned) and counted;
- a window is handed to Paho at once and each PUBACK is awaited against one
  deadline. A PUBACK never deletes a row.

`/health.committed_receipts.catch_up` reports window, rate cap, in flight,
sweeps, windows, rows resent, publish failures, stalls and skipped rows by
reason. `replay_attempts_total`, `replay_pubacks_total`,
`replay_failures_total` and `replay_next_retry_seconds` now report the
catch-up. `CommittedReceiptReplay` (head replay) stays in the module but the
runtime no longer uses it.

**Central publisher.** `CommittedReceiptPublisher.run_batch` claims up to
`NEXOLAB_RECEIPT_PUBLISHER_BATCH_SIZE` (default 50, 1..500) due intents in
commit order with `FOR UPDATE SKIP LOCKED`, takes each durable retry lease in
one committed transaction, publishes them, and marks `published_at` per
intent only after that intent's own PUBACK (same `attempts`/`receipt_id`
guard as before). The earlier rule that an unpublished older receipt blocks
newer receipts of the same node is removed: the Edge no longer needs order.
`CommittedReceiptMqttSender.send_batch` validates every message like the
single-message path, hands the batch to Paho and reports each PUBACK. The
ingestion commit path wakes the publisher (`CommittedReceiptIngress` calls
`CommittedReceiptPublisherLoop.wake` after the telemetry and receipt intent
commit), so the 1.0 s idle poll is only a fallback. Retry backoff is never
shortened by wakes. The outbox bound and the outbox-full legacy fallback are
unchanged. `run_once` remains as a one-intent batch.

The acceptance gate and measured numbers are in
`docs/operations/committed-receipt-acceptance.md`. Hardware and site remain
**UNVERIFIED**.
