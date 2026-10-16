# NEXOLAB #1394 — durable telemetry during a disconnected central consumer

**Scope:** offline delivery discovery only. No production MQTT, Device Agent,
database, Compose, serial device, or service modification.

## Observed source contract

| Boundary                       | Actual checked implementation                                                                        | Consequence                                                                       |
| ------------------------------ | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Edge observation → SQLite      | `services/device-agent/main.py` queues an event with stable `event_id` and sequence before publish   | Local persistence until MQTT publish acknowledgement                              |
| SQLite → broker                | `flush_queue` sends QoS 1 and deletes the SQLite row after `wait_for_publish` / `is_published`       | Deletion proves **broker PUBACK**, not durable API/DB acceptance                  |
| Central broker                 | `mosquitto.central.conf` has `persistence true`, `autosave_interval 60`, `max_queued_messages 10000` | Offline persistent subscribers are bounded; broker capacity is not infinite       |
| MQTT broker → central consumer | `mqtt_consumer.py`: if durable spool enabled, MQTT 3.1.1 `clean_session=False`, `manual_ack=True`    | A connected central consumer acknowledges **after staging** the message           |
| Central staging → PostgreSQL   | `ingestion.py` has local durable ingestion spool, retries and event-ID deduplication                 | Once a record is staged locally, backend DB downtime can be handled independently |

The deployed API returned HTTP 503 `database=ready,mqtt=not_ready` after
2026-10-16 reboot while the edge reported MQTT connected and queue=0.
**These observations alone do not establish loss of particular production samples.**
Old Graph/history contents must be reconciled via indexed event IDs/sequence
before any claim about actual missing measurements.

## Isolated MQTT experiment on the physical ARM64 host

Run:

```bash
bash scripts/tests/mqtt-offline-subscriber-cap-1394.sh
```

The fixture uses the **locally available** `eclipse-mosquitto:2.0.22` image
with `--network none`, no published ports, an ephemeral tmpfs broker store,
read-only rootfs, bounded memory/CPU/pids, and an owner-created temporary
configuration. It never touches production messages or volumes.

- Use `max_queued_messages=10` **in the fixture only**; production setting is 10000.
- Establish a durable MQTT 3.1.1 QoS 1 subscription, disconnect the consumer.
- Publish 15 QoS 1 events while the subscriber is absent.
- Reconnect using its prior client ID / persistent session.
- **Observed:** 15 broker-accepted messages, **10 recovered**, **5 unrecovered**.
  Command exited 0 and printed `RESULT=PASS_BOUNDED_BROKER_QUEUE_CAN_DROP_ACKED_MESSAGES`.
- This demonstrates the **class of failure** with a deliberately small cap.
  It is not evidence that live production has dropped five messages, nor does
  it establish the exact production duration before its larger queue fills.

## Decision / release gate

**BLOCKED for an unconditional no-data-loss guarantee.** Broker persistence,
QoS 1, and a central manual ACK are useful but do not implement an edge-to-
PostgreSQL end-to-end durability acknowledgement. When the subscriber stays
unreachable and its broker queue exceeds a finite cap, edge SQLite entries
have already been removed after broker PUBACK.

A later narrowly scoped implementation Work Package must add an application-
level **durable central acknowledgement/replay contract**, without altering
read-only Modbus operations. Recommended design gate:

1. Keep immutable `event_id` and monotonic per-stream sequence with a bounded
   local SQLite retention/outbox policy; do not delete solely on MQTT PUBACK.
2. Central sends a node-authenticated receipt only once an `event_id` is
   durably accepted by **central local spool or PostgreSQL**, with receipt
   provenance explicitly distinguishing these two levels. For a stronger
   persisted guarantee, send final receipt after committed PostgreSQL.
3. Edge only prunes entries after durable receipt of matching IDs/ranges;
   retries across broker/API restarts must be idempotent. Prevent an ACK
   for a later sequence from concealing a missing earlier event.
4. Specify subscriber session expiry, outbox/broker capacity and disk-full
   behavior, alarm thresholds, bounded catch-up rate, retry backpressure,
   resource caps and offline retention expectations.
5. Include automated isolated tests for API-down/broker-up, broker-down,
   subscriber backlog saturation, device restart, stale ACK, duplicate ACK,
   out-of-order arrivals, PostgreSQL outage/recovery and disk-full.
6. After software acceptance, verify real ARM64 read-only acquisition, central
   persisted IDs, charts/CSV history and actual LAN/HTTPS recovery. No hardware
   acceptance without that evidence.

This discovery does not implement (or pretend to implement) the new ACK path.
Keep #189 overall recovery acceptance open. No direct production update,
Modbus write, Docker network repair, site restart or volume deletion is allowed
by this document.
