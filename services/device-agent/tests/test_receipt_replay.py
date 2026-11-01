"""Source-only bounded FIFO replay; never touches installed broker or hardware."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from durable_receipt_v1 import ReceiptProtocolError
from receipt_replay import CommittedReceiptReplay
from receipt_retention import CommittedReceiptQueue

ORG = "00000000-0000-0000-0000-000000000001"
NODE = "edge-01"
TOPIC = f"nexolab/v1/{ORG}/{NODE}/telemetry"
RECEIPT_TOPIC = f"nexolab/v1/{ORG}/{NODE}/receipts"


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "outbox.db"
        self.queue = CommittedReceiptQueue(self.path)
        self.addCleanup(self.queue._connection.close)
        self.replay = CommittedReceiptReplay(
            self.queue,
            organization_id=ORG,
            node_id=NODE,
            initial_retry_seconds=5.0,
            max_retry_seconds=20.0,
        )
        self.sent: list[tuple[str, str]] = []

    def pending(
        self, *, topic: str = TOPIC, node_id: str = NODE, **extra: object
    ) -> str:
        event_id = str(uuid.uuid4())
        payload = {"event_id": event_id, "node_id": node_id, "value": 3.8}
        payload.update(extra)
        self.queue.enqueue_with_sequence(
            topic, payload, event_id, stream="telemetry"
        )
        return event_id

    def puback(self, topic: str, payload: str) -> bool:
        self.sent.append((topic, payload))
        return True

    def receipt(self, event_id: str, sequence: int, *, level: str = "postgres_committed") -> bytes:
        return json.dumps({
            "contract_version": 1,
            "receipt_id": str(uuid.uuid4()),
            "event_id": event_id,
            "organization_id": ORG,
            "node_id": NODE,
            "stream": "telemetry",
            "node_sequence": sequence,
            "receipt_level": level,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }).encode()

    def apply(self, raw: bytes) -> str:
        return self.queue.apply_committed_receipt(
            raw, topic=RECEIPT_TOPIC, organization_id=ORG,
            node_id=NODE, central_publisher_authorized=True,
        )

    def test_empty_queue_does_not_publish(self) -> None:
        self.assertEqual(
            self.replay.attempt_once(self.puback, now_monotonic=0), "empty"
        )
        self.assertEqual(self.sent, [])

    def test_broker_puback_never_prunes_and_is_throttled(self) -> None:
        event_id = self.pending()
        self.assertEqual(
            self.replay.attempt_once(self.puback, now_monotonic=10),
            "puback_waiting_receipt",
        )
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(json.loads(self.sent[0][1])["event_id"], event_id)
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=14), "deferred")
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=15), "puback_waiting_receipt")
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=24), "deferred")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.queue.size(), 1)
        stats = self.replay.snapshot(now_monotonic=24)
        self.assertEqual(stats["broker_pubacks_total"], 2)
        self.assertEqual(stats["next_retry_seconds"], 1)
        self.assertIs(stats["postgres_committed"], False)

    def test_retry_backoff_is_capped_and_one_per_tick(self) -> None:
        self.pending()
        attempts: list[int] = []

        def fail(_topic: str, _payload: str) -> bool:
            attempts.append(1)
            return False

        for t in (0, 5, 15, 35, 55):
            self.assertEqual(self.replay.attempt_once(fail, now_monotonic=t), "retry_scheduled")
        self.assertEqual(self.replay.attempt_once(fail, now_monotonic=70), "deferred")
        self.assertEqual(len(attempts), 5)
        stats = self.replay.snapshot(now_monotonic=70)
        self.assertEqual(stats["publish_failures_total"], 5)
        self.assertEqual(stats["next_retry_seconds"], 5)
        self.assertEqual(self.queue.size(), 1)

    def test_publish_network_exception_is_bounded_and_no_deletion(self) -> None:
        self.pending()

        def broken(_topic: str, _payload: str) -> bool:
            raise OSError("synthetic network failure")

        self.assertEqual(self.replay.attempt_once(broken, now_monotonic=1), "retry_scheduled")
        self.assertEqual(self.replay.attempt_once(broken, now_monotonic=2), "deferred")
        self.assertEqual(self.queue.size(), 1)

    def test_truthy_non_boolean_is_not_qos_puback(self) -> None:
        self.pending()
        self.assertEqual(
            self.replay.attempt_once(lambda _t, _p: 1, now_monotonic=1),
            "retry_scheduled",
        )
        self.assertEqual(self.queue.size(), 1)

    def test_fifo_does_not_skip_until_actual_committed_receipt(self) -> None:
        first = self.pending()
        second = self.pending()
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=1), "puback_waiting_receipt")
        self.assertEqual(json.loads(self.sent[0][1])["event_id"], first)
        self.assertEqual(self.apply(self.receipt(first, 1)), "prune_allowed")
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=2), "puback_waiting_receipt")
        self.assertEqual(json.loads(self.sent[1][1])["event_id"], second)
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(self.apply(self.receipt(second, 2)), "prune_allowed")
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=3), "empty")

    def test_informational_receipt_does_not_clear_queue(self) -> None:
        first = self.pending()
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=0), "puback_waiting_receipt")
        self.assertEqual(self.apply(self.receipt(first, 1, level="durably_spooled")), "informational")
        self.assertEqual(self.queue.size(), 1)

    def test_restart_preserves_pending_record(self) -> None:
        event_id = self.pending()
        self.assertEqual(self.replay.attempt_once(self.puback, now_monotonic=0), "puback_waiting_receipt")
        other = CommittedReceiptReplay(
            self.queue, organization_id=ORG, node_id=NODE
        )
        self.assertEqual(other.attempt_once(self.puback, now_monotonic=1), "puback_waiting_receipt")
        self.assertEqual(json.loads(self.sent[-1][1])["event_id"], event_id)
        self.assertEqual(self.queue.size(), 1)

    def test_legacy_unscoped_topic_fail_closed_without_skipping(self) -> None:
        self.pending(topic="nexolab/telemetry")
        self.pending()
        self.assertEqual(
            self.replay.attempt_once(self.puback, now_monotonic=1),
            "blocked_foreign_queue_topic",
        )
        self.assertEqual(len(self.sent), 0)
        self.assertEqual(self.queue.size(), 2)

    def test_wrong_tenant_topic_blocked(self) -> None:
        self.pending(topic=f"nexolab/v1/{uuid.uuid4()}/{NODE}/telemetry")
        self.assertEqual(
            self.replay.attempt_once(self.puback, now_monotonic=1),
            "blocked_foreign_queue_topic",
        )
        self.assertEqual(self.sent, [])

    def test_payload_column_drift_prevents_replay(self) -> None:
        event_id = self.pending()
        with self.queue._connection:
            self.queue._connection.execute(
                "UPDATE outbound_queue SET event_id=? WHERE event_id=?",
                (str(uuid.uuid4()), event_id),
            )
        with self.assertRaisesRegex(ReceiptProtocolError, "invalid_local_replay_identity"):
            self.replay.attempt_once(self.puback, now_monotonic=1)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.queue.size(), 1)

    def test_wrong_node_payload_prevents_replay(self) -> None:
        self.pending(node_id="edge-other")
        with self.assertRaisesRegex(ReceiptProtocolError, "invalid_local_replay_identity"):
            self.replay.attempt_once(self.puback, now_monotonic=1)
        self.assertEqual(self.sent, [])

    def test_duplicate_json_keys_prevent_replay(self) -> None:
        event_id = self.pending()
        corrupt = '{"event_id":"' + event_id + '","event_id":"' + event_id + '"}'
        with self.queue._connection:
            self.queue._connection.execute(
                "UPDATE outbound_queue SET payload=? WHERE event_id=?",
                (corrupt, event_id),
            )
        with self.assertRaisesRegex(ReceiptProtocolError, "duplicate_local_pending_json_key"):
            self.replay.attempt_once(self.puback, now_monotonic=1)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.queue.size(), 1)

    def test_invalid_sequence_prevents_replay(self) -> None:
        event_id = self.pending()
        with self.queue._connection:
            self.queue._connection.execute(
                "UPDATE outbound_queue SET payload=? WHERE event_id=?",
                (json.dumps({"event_id":event_id,"node_id": NODE,"node_sequence": 0}), event_id),
            )
        with self.assertRaisesRegex(ReceiptProtocolError, "invalid_local_replay_identity"):
            self.replay.attempt_once(self.puback, now_monotonic=1)
        self.assertEqual(self.sent, [])

    def test_capacity_snapshot_is_read_only_and_reports_pending_bytes(self) -> None:
        first = self.pending()
        snapshot = self.queue.replay_capacity_snapshot()
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["pending_count"], 1)
        self.assertGreater(snapshot["pending_payload_bytes"], 0)
        self.assertGreater(snapshot["sqlite_file_bytes"], 0)
        self.assertGreater(snapshot["filesystem_free_bytes"], 0)
        self.assertGreaterEqual(snapshot["oldest_pending_age_seconds"], 0)
        self.assertIs(snapshot["oldest_timestamp_valid"], True)
        self.assertIs(snapshot["retention_guaranteed"], False)
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(self.apply(self.receipt(first, 1)), "prune_allowed")
        self.assertEqual(self.queue.replay_capacity_snapshot()["pending_count"], 0)
        self.assertIsNone(
            self.queue.replay_capacity_snapshot()["oldest_pending_age_seconds"]
        )

    def test_corrupt_oldest_timestamp_is_unverified_not_zero(self) -> None:
        event_id = self.pending()
        with self.queue._connection:
            self.queue._connection.execute(
                "UPDATE outbound_queue SET created_at='not-an-iso-time' WHERE event_id=?",
                (event_id,),
            )
        snapshot = self.queue.replay_capacity_snapshot()
        self.assertIsNone(snapshot["oldest_pending_age_seconds"])
        self.assertIs(snapshot["oldest_timestamp_valid"], False)
        self.assertEqual(self.queue.size(), 1)

    def test_invalid_policy_clock_and_identity_are_rejected(self) -> None:
        for invalid in (float("nan"), float("inf"), -1):
            with self.assertRaises(ValueError):
                self.replay.attempt_once(self.puback, now_monotonic=invalid)
        with self.assertRaises(ValueError):
            CommittedReceiptReplay(self.queue, organization_id="notuuid", node_id=NODE)
        with self.assertRaises(ValueError):
            CommittedReceiptReplay(self.queue, organization_id=ORG, node_id="bad/#")
        with self.assertRaises(ValueError):
            CommittedReceiptReplay(self.queue, organization_id=ORG, node_id=NODE, initial_retry_seconds=0)
        with self.assertRaises(ValueError):
            CommittedReceiptReplay(self.queue, organization_id=ORG, node_id=NODE, initial_retry_seconds=10, max_retry_seconds=5)


if __name__ == "__main__":
    unittest.main()
