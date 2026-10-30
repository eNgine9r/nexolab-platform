"""Isolated SQLite receipt-ledger tests; production DeviceAgent remains unwired."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from durable_receipt_v1 import ReceiptProtocolError
from receipt_retention import CommittedReceiptQueue

ORG = "00000000-0000-0000-0000-000000000001"
NODE = "edge-01"
TOPIC = f"nexolab/v1/{ORG}/{NODE}/telemetry"
RECEIPT_TOPIC = f"nexolab/v1/{ORG}/{NODE}/receipts"


class CommittedReceiptLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "outbox.db"
        self.queue = CommittedReceiptQueue(self.db_path)

    def pending(self, count: int = 1) -> list[str]:
        ids = []
        for _ in range(count):
            event_id = str(uuid.uuid4())
            payload = {"event_id": event_id, "node_id": NODE, "value": 9.2}
            self.queue.enqueue_with_sequence(TOPIC, payload, event_id, stream="telemetry")
            ids.append(event_id)
        return ids

    def receipt(
        self,
        event_id: str,
        sequence: int = 1,
        *,
        level: str = "postgres_committed",
        overrides: dict[str, object] | None = None,
    ) -> bytes:
        message: dict[str, object] = {
            "contract_version": 1,
            "receipt_id": str(uuid.uuid4()),
            "event_id": event_id,
            "organization_id": ORG,
            "node_id": NODE,
            "stream": "telemetry",
            "node_sequence": sequence,
            "receipt_level": level,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
        }
        message.update(overrides or {})
        return json.dumps(message).encode("utf-8")

    def apply(self, raw: bytes, *, auth: bool = True, topic: str = RECEIPT_TOPIC) -> str:
        return self.queue.apply_committed_receipt(
            raw,
            topic=topic,
            organization_id=ORG,
            node_id=NODE,
            central_publisher_authorized=auth,
        )

    def test_final_receipt_deletes_exactly_oldest_and_persists_replay_ledger(self) -> None:
        first, second = self.pending(2)
        raw = self.receipt(first)
        self.assertEqual(self.apply(raw), "prune_allowed")
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(json.loads(self.queue.oldest()[0][2])["event_id"], second)
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_id_already_processed"):
            self.apply(raw)
        self.assertEqual(self.apply(self.receipt(second, 2)), "prune_allowed")
        self.assertEqual(self.queue.size(), 0)

    def test_spool_only_is_informational_and_duplicate_is_rejected(self) -> None:
        (event_id,) = self.pending()
        raw = self.receipt(event_id, level="durably_spooled")
        self.assertEqual(self.apply(raw), "informational")
        self.assertEqual(self.queue.size(), 1)
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_id_already_processed"):
            self.apply(raw)
        self.assertEqual(self.apply(self.receipt(event_id)), "prune_allowed")

    def test_unauthorized_cannot_delete_or_create_ledger(self) -> None:
        (event_id,) = self.pending()
        with self.assertRaisesRegex(ReceiptProtocolError, "central_publisher_not_authenticated"):
            self.apply(self.receipt(event_id), auth=False)
        self.assertEqual(self.queue.size(), 1)
        rows = self.queue._connection.execute(
            "SELECT name FROM sqlite_master WHERE name='committed_receipt_ledger'"
        ).fetchall()
        self.assertEqual(rows, [])

    def test_wrong_topic_node_event_sequence_and_staleness_are_rejected(self) -> None:
        first, second = self.pending(2)
        invalid = [
            (self.receipt(second, 2), RECEIPT_TOPIC),
            (self.receipt(first, overrides={"organization_id": str(uuid.uuid4())}), RECEIPT_TOPIC),
            (self.receipt(first, overrides={"node_id": "edge-02"}), RECEIPT_TOPIC),
            (self.receipt(first, overrides={"event_id": str(uuid.uuid4())}), RECEIPT_TOPIC),
            (self.receipt(first, overrides={"node_sequence": 5}), RECEIPT_TOPIC),
            (self.receipt(first), f"nexolab/v1/{ORG}/edge-02/receipts"),
            (self.receipt(first, overrides={
                "accepted_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(),
            }), RECEIPT_TOPIC),
        ]
        for raw, topic in invalid:
            with self.subTest(raw=raw):
                with self.assertRaises(ReceiptProtocolError):
                    self.apply(raw, topic=topic)
                self.assertEqual(self.queue.size(), 2)

    def test_receipt_replay_rejected_across_process_restart(self) -> None:
        (event_id,) = self.pending()
        raw = self.receipt(event_id)
        self.apply(raw)
        reopened = CommittedReceiptQueue(self.db_path)
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_id_already_processed"):
            reopened.apply_committed_receipt(
                raw,
                topic=RECEIPT_TOPIC,
                organization_id=ORG,
                node_id=NODE,
                central_publisher_authorized=True,
            )

    def test_deletion_trigger_failure_rolls_back_receipt_ledger(self) -> None:
        (event_id,) = self.pending()
        # Persist an informational receipt first so the table definitely
        # exists outside the failed final-ACK transaction. The final receipt's
        # new ledger insert must roll back, leaving only this earlier entry.
        self.assertEqual(
            self.apply(self.receipt(event_id, level="durably_spooled")),
            "informational",
        )
        raw = self.receipt(event_id)
        self.queue._connection.execute(
            """
            CREATE TRIGGER prevent_receipt_delete
            BEFORE DELETE ON outbound_queue
            BEGIN SELECT RAISE(ABORT, 'test crash before delete'); END
            """
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply(raw)
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(self.queue._connection.execute(
            "SELECT COUNT(*) FROM committed_receipt_ledger"
        ).fetchone()[0], 1)
        self.queue._connection.execute("DROP TRIGGER prevent_receipt_delete")
        self.assertEqual(self.apply(raw), "prune_allowed")

    def test_shared_contract_copy_must_remain_byte_exact(self) -> None:
        root = Path(__file__).resolve().parents[3]
        self.assertEqual(
            (root / "contracts/durable_receipt_v1.py").read_bytes(),
            (root / "services/device-agent/durable_receipt_v1.py").read_bytes(),
        )

    def test_legacy_device_agent_uses_legacy_queue_not_opt_in_receipt_queue(self) -> None:
        from main import DeviceAgent, OfflineQueue
        self.assertIsNot(CommittedReceiptQueue, OfflineQueue)
        self.assertEqual(DeviceAgent.__init__.__code__.co_names.count("OfflineQueue"), 1)
