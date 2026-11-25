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

    def set_pending_payload(self, event_id: str, payload: str) -> None:
        # Commit synthetic corruption before the receipt transaction starts.
        with self.queue._connection:
            self.queue._connection.execute(
                "UPDATE outbound_queue SET payload=? WHERE event_id=?",
                (payload, event_id),
            )

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

    def test_inherited_puback_delete_path_is_rejected_without_pruning(self) -> None:
        (event_id,) = self.pending()
        record_id = self.queue._connection.execute(
            "SELECT id FROM outbound_queue WHERE event_id=?", (event_id,)
        ).fetchone()[0]
        with self.assertRaisesRegex(
            ReceiptProtocolError, "postgres_committed_receipt_required"
        ):
            self.queue.delete(int(record_id))
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(self.apply(self.receipt(event_id)), "prune_allowed")
        self.assertEqual(self.queue.size(), 0)

    def test_final_receipt_deletes_exactly_its_row_and_persists_replay_ledger(self) -> None:
        first, second = self.pending(2)
        raw = self.receipt(first)
        self.assertEqual(self.apply(raw), "prune_allowed")
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(json.loads(self.queue.oldest()[0][2])["event_id"], second)
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_id_already_processed"):
            self.apply(raw)
        self.assertEqual(self.apply(self.receipt(second, 2)), "prune_allowed")
        self.assertEqual(self.queue.size(), 0)

    def ledger_rows(self) -> int:
        exists = self.queue._connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='committed_receipt_ledger'"
        ).fetchone()[0]
        if not exists:
            return 0
        return int(self.queue._connection.execute(
            "SELECT COUNT(*) FROM committed_receipt_ledger"
        ).fetchone()[0])

    def test_out_of_order_receipt_prunes_only_its_exact_pending_row(self) -> None:
        # #1762 slice 4: exact-row binding replaces the FIFO-head rule.
        first, second, third = self.pending(3)
        self.assertEqual(self.apply(self.receipt(third, 3)), "prune_allowed")
        self.assertEqual(
            [row[0] for row in self.queue._connection.execute(
                "SELECT event_id FROM outbound_queue ORDER BY id"
            )],
            [first, second],
        )
        self.assertEqual(self.ledger_rows(), 1)
        # A receipt for the already pruned row (fresh receipt_id) is rejected.
        with self.assertRaisesRegex(ReceiptProtocolError, "no_matching_pending_telemetry"):
            self.apply(self.receipt(third, 3))
        # An unknown event is rejected and never prunes another row.
        with self.assertRaisesRegex(ReceiptProtocolError, "no_matching_pending_telemetry"):
            self.apply(self.receipt(str(uuid.uuid4()), 2))
        # A receipt naming one row with another row's sequence never prunes.
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_sequence_mismatch"):
            self.apply(self.receipt(second, 1))
        self.assertEqual(self.queue.size(), 2)
        self.assertEqual(self.ledger_rows(), 1)
        self.assertEqual(self.apply(self.receipt(second, 2)), "prune_allowed")
        self.assertEqual(self.apply(self.receipt(first, 1)), "prune_allowed")
        self.assertEqual(self.queue.size(), 0)
        self.assertEqual(self.ledger_rows(), 3)

    def test_foreign_rows_are_never_pruned_and_do_not_block_scoped_rows(self) -> None:
        for foreign_topic in (
            "nexolab/telemetry",
            f"nexolab/v1/{uuid.uuid4()}/{NODE}/telemetry",
            f"nexolab/v1/{ORG}/{NODE}/health",
            f"nexolab/v1/{ORG}/edge-02/telemetry",
        ):
            with self.subTest(foreign_topic=foreign_topic):
                foreign_event = str(uuid.uuid4())
                self.queue.enqueue(
                    foreign_topic,
                    json.dumps({
                        "event_id": foreign_event, "node_id": NODE, "node_sequence": 1,
                    }),
                    foreign_event,
                )
                (scoped_event,) = self.pending()
                scoped_sequence = json.loads(self.queue.oldest()[1][2])["node_sequence"]
                ledger_before = self.ledger_rows()
                # A receipt that names the foreign row is rejected fail-closed.
                with self.assertRaisesRegex(
                    ReceiptProtocolError, "pending_row_topic_not_scoped"
                ):
                    self.apply(self.receipt(foreign_event, 1))
                self.assertEqual(self.queue.size(), 2)
                self.assertEqual(self.ledger_rows(), ledger_before)
                # The scoped row behind it prunes on its own exact receipt.
                self.assertEqual(
                    self.apply(self.receipt(scoped_event, scoped_sequence)),
                    "prune_allowed",
                )
                self.assertEqual(
                    [row[0] for row in self.queue._connection.execute(
                        "SELECT event_id FROM outbound_queue ORDER BY id"
                    )],
                    [foreign_event],
                )
                # Synthetic fixture-only removal of the foreign row; public
                # receipt-mode delete() must remain forbidden.
                with self.queue._connection:
                    self.queue._connection.execute(
                        "DELETE FROM outbound_queue WHERE event_id=?", (foreign_event,)
                    )

    def test_older_foreign_queue_row_remains_after_informational_receipt(self) -> None:
        foreign_id = str(uuid.uuid4())
        self.queue.enqueue("nexolab/telemetry", "{}", foreign_id)
        (scoped_event,) = self.pending()
        raw = self.receipt(scoped_event, level="durably_spooled")
        self.assertEqual(self.apply(raw), "informational")
        self.assertEqual(
            [row[0] for row in self.queue._connection.execute(
                "SELECT event_id FROM outbound_queue ORDER BY id"
            )],
            [foreign_id, scoped_event],
        )
        with self.assertRaisesRegex(ReceiptProtocolError, "receipt_id_already_processed"):
            self.apply(raw)

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
            (self.receipt(second, 1), RECEIPT_TOPIC),
            (self.receipt(first, 2), RECEIPT_TOPIC),
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



    def test_tampered_local_pending_identity_never_prunes(self) -> None:
        (event_id,) = self.pending()
        original = self.queue.oldest()[0][2]
        for corrupt in (
            {"event_id": str(uuid.uuid4())},
            {"node_id": "edge-02"},
            {"organization_id": str(uuid.uuid4())},
            {"stream": "health"},
        ):
            with self.subTest(corrupt=corrupt):
                payload = {**json.loads(original), **corrupt}
                self.set_pending_payload(event_id, json.dumps(payload))
                with self.assertRaisesRegex(
                    ReceiptProtocolError, "local_pending_identity_mismatch"
                ):
                    self.apply(self.receipt(event_id))
                self.assertEqual(self.queue.size(), 1)
                # Even a rejected receipt must not persist a replay ID.
                self.assertEqual(
                    self.queue._connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE name='committed_receipt_ledger'"
                    ).fetchall(),
                    [],
                )
        self.set_pending_payload(event_id, original)
        self.assertEqual(self.apply(self.receipt(event_id)), "prune_allowed")

    def test_duplicate_keys_in_local_pending_payload_fail_closed(self) -> None:
        (event_id,) = self.pending()
        original = self.queue.oldest()[0][2]
        duplicate_json = original.replace('"node_id":', '"node_id":"edge-02","node_id":')
        self.set_pending_payload(event_id, duplicate_json)
        with self.assertRaisesRegex(
            ReceiptProtocolError, "invalid_local_pending_payload"
        ):
            self.apply(self.receipt(event_id))
        self.assertEqual(self.queue.size(), 1)
        self.set_pending_payload(event_id, original)
        self.assertEqual(self.apply(self.receipt(event_id)), "prune_allowed")

    def test_future_receipt_and_duplicate_keys_never_prune(self) -> None:
        (event_id,) = self.pending()
        future = self.receipt(
            event_id,
            overrides={
                "accepted_at": (
                    datetime.now(timezone.utc) + timedelta(minutes=6)
                ).isoformat()
            },
        )
        raw = self.receipt(event_id)
        duplicate = raw.replace(b'"node_id":', b'"node_id":"edge-02","node_id":')
        for rejected in (future, duplicate):
            with self.subTest(receipt=rejected):
                with self.assertRaises(ReceiptProtocolError):
                    self.apply(rejected)
                self.assertEqual(self.queue.size(), 1)
        self.assertEqual(self.apply(self.receipt(event_id)), "prune_allowed")

    def test_sqlite_full_during_receipt_transaction_rolls_back_and_recovers(self) -> None:
        # PRAGMA max_page_count confines the failure to a disposable SQLite
        # fixture without filling the Raspberry disk. This exercises the real
        # SQLITE_FULL failure, not a mocked connection or injected exception.
        (event_id,) = self.pending()
        raw = self.receipt(event_id)
        original_page_limit = self.queue._connection.execute(
            "PRAGMA max_page_count"
        ).fetchone()[0]
        current_pages = self.queue._connection.execute(
            "PRAGMA page_count"
        ).fetchone()[0]
        self.queue._connection.execute(f"PRAGMA max_page_count = {current_pages}")
        try:
            self.assertEqual(
                self.queue._connection.execute(
                    "PRAGMA max_page_count"
                ).fetchone()[0],
                current_pages,
            )
            with self.assertRaisesRegex(
                sqlite3.OperationalError, "database or disk is full"
            ):
                self.apply(raw)
            self.assertFalse(self.queue._connection.in_transaction)
            self.assertEqual(self.queue.size(), 1)
            self.assertEqual(
                self.queue._connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE name='committed_receipt_ledger'"
                ).fetchall(),
                [],
            )
        finally:
            # Restore only the synthetic fixture's SQLite page budget.
            self.queue._connection.execute(
                f"PRAGMA max_page_count = {original_page_limit}"
            )
        self.assertEqual(self.apply(raw), "prune_allowed")
        self.assertEqual(self.queue.size(), 0)

    def test_contended_sqlite_transaction_preserves_row_and_recovers(self) -> None:
        (event_id,) = self.pending()
        raw = self.receipt(event_id)
        bounded = CommittedReceiptQueue(
            self.db_path,
            busy_timeout_ms=10,
            busy_retry_attempts=2,
            busy_retry_delay_seconds=0.01,
        )
        blocker = sqlite3.connect(self.db_path, timeout=0)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                bounded.apply_committed_receipt(
                    raw,
                    topic=RECEIPT_TOPIC,
                    organization_id=ORG,
                    node_id=NODE,
                    central_publisher_authorized=True,
                )
        finally:
            blocker.rollback()
            blocker.close()
        self.assertEqual(self.queue.size(), 1)
        self.assertEqual(
            bounded.apply_committed_receipt(
                raw,
                topic=RECEIPT_TOPIC,
                organization_id=ORG,
                node_id=NODE,
                central_publisher_authorized=True,
            ),
            "prune_allowed",
        )
        self.assertEqual(bounded.size(), 0)

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
