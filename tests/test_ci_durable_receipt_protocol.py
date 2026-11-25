"""Hermetic v1 durability receipt security and exact-row binding regression."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "contracts" / "durable_receipt_v1.py"
SPEC = importlib.util.spec_from_file_location("nexolab_receipt_v1", SRC)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

EVENT = "a1f59453-86e3-43f7-b093-c814b20d5cc5"
RECEIPT = "a21f4e73-83b6-4ead-86c5-f8ba5c7fb6e1"
ORG = "28dceec5-3a75-4d03-b5ec-b21122b35778"
NODE = "edge-01"
TOPIC = f"nexolab/v1/{ORG}/{NODE}/receipts"


def payload(**kwargs):
    receipt = {
        "contract_version": 1,
        "receipt_id": RECEIPT,
        "event_id": EVENT,
        "organization_id": ORG,
        "node_id": NODE,
        "stream": "telemetry",
        "node_sequence": 41,
        "receipt_level": "postgres_committed",
        "accepted_at": "2026-10-16T12:01:02Z",
    }
    receipt.update(kwargs)
    return json.dumps(receipt, sort_keys=True).encode()


def verify(message=None, **kwargs):
    expected = {
        "topic": TOPIC,
        "central_publisher_authorized": True,
        "expected_event_id": EVENT,
        "expected_organization_id": ORG,
        "expected_node_id": NODE,
        "expected_node_sequence": 41,
        "pending_row_topic": f"nexolab/v1/{ORG}/{NODE}/telemetry",
        "seen_receipt_ids": frozenset(),
        "now": datetime(2026, 10, 16, 12, 2, tzinfo=timezone.utc),
    }
    expected.update(kwargs)
    return mod.validate_for_pending(message if message is not None else payload(), **expected)


class DurableReceiptV1ContractTests(unittest.TestCase):
    def test_schema_matches_minimal_protocol(self):
        schema = json.loads((ROOT / "contracts/telemetry-durable-receipt.v1.schema.json").read_text())
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertTrue(schema["additionalProperties"] is False)
        self.assertEqual(set(schema["required"]), mod.FIELDS)
        self.assertEqual(set(schema["properties"]), mod.FIELDS)
        self.assertEqual(schema["properties"]["receipt_level"]["enum"],
                         ["durably_spooled", "postgres_committed"])

    def test_final_commit_receipt_prunes_its_exact_pending_row(self):
        self.assertEqual(verify(), "prune_allowed")

    def test_durable_spool_receipt_is_informational_only(self):
        self.assertEqual(verify(payload(receipt_level="durably_spooled")),
                         "informational")

    def test_unauthorized_broker_publisher_never_prunes(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "not_authenticated"):
            verify(central_publisher_authorized=False)

    def test_wrong_topic_blocks_even_when_envelope_matches(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "topic_identity_mismatch"):
            verify(topic="nexolab/v1/other/edge-01/receipts")

    def test_wrong_event_id_blocks(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "identity_mismatch"):
            verify(payload(event_id="e5f898f9-2820-4e49-a754-d32e677baeed"))

    def test_wrong_node_and_tenant_block(self):
        for changed in (
            {"node_id": "edge-02"},
            {"organization_id": "a61b0830-4e78-479b-8e10-8d1e1123ba88"},
            {"stream": "health"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(mod.ReceiptProtocolError, "identity_mismatch"):
                    verify(payload(**changed))

    def test_wrong_node_sequence_blocks(self):
        for value in (40, 42, True, "41"):
            with self.subTest(value=value):
                with self.assertRaises(mod.ReceiptProtocolError):
                    verify(payload(node_sequence=value))

    def test_out_of_order_receipt_is_accepted_only_for_its_exact_pending_row(self):
        # #1762 slice 4: a receipt for a non-head row prunes only when every
        # identity field matches that exact row; it can never name another.
        self.assertEqual(verify(payload(node_sequence=57), expected_node_sequence=57),
                         "prune_allowed")
        for row in (
            {"expected_node_sequence": 40},
            {"expected_node_sequence": 42},
            {"expected_event_id": "e5f898f9-2820-4e49-a754-d32e677baeed"},
        ):
            with self.subTest(row=row):
                with self.assertRaisesRegex(mod.ReceiptProtocolError, "mismatch"):
                    verify(**row)

    def test_pending_row_must_be_this_nodes_scoped_telemetry(self):
        for row_topic in (
            "nexolab/telemetry",
            f"nexolab/v1/{ORG}/{NODE}/health",
            f"nexolab/v1/{ORG}/edge-02/telemetry",
            "nexolab/v1/a61b0830-4e78-479b-8e10-8d1e1123ba88/edge-01/telemetry",
            None,
        ):
            with self.subTest(row_topic=row_topic):
                with self.assertRaisesRegex(mod.ReceiptProtocolError,
                                            "pending_row_topic_not_scoped"):
                    verify(pending_row_topic=row_topic)

    def test_spooled_receipt_never_deletes_even_for_exact_row(self):
        self.assertEqual(verify(payload(receipt_level="durably_spooled")),
                         "informational")

    def test_malformed_durability_level_never_raises_unchecked_type_error(self):
        for value in (["postgres_committed"], {"value": "postgres_committed"}, 1, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(mod.ReceiptProtocolError, "durability_level"):
                    verify(payload(receipt_level=value))

    def test_unsupported_version_blocks(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "version"):
            verify(payload(contract_version=2))

    def test_extra_missing_and_duplicate_fields_block(self):
        receipt = json.loads(payload())
        receipt["suspicious"] = True
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "fields"):
            verify(json.dumps(receipt).encode())
        del receipt["suspicious"]
        del receipt["node_id"]
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "fields"):
            verify(json.dumps(receipt).encode())
        duplicated = payload().decode().replace('"contract_version": 1,',
                                                  '"contract_version": 1, "contract_version": 1,')
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "duplicate"):
            verify(duplicated.encode())

    def test_malformed_json_bytes_and_excess_payload_block(self):
        for message in (b"{", b"\xff", b"x"*2049, b""):
            with self.subTest(message=message[:8]):
                with self.assertRaises(mod.ReceiptProtocolError):
                    verify(message)

    def test_receipt_id_must_be_canonical_uuid(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "uuid"):
            verify(payload(receipt_id="not-uuid"))

    def test_invalid_or_naive_timestamp_blocks(self):
        for stamp in ("2026-10-16T12:01:02", "bad", ""):
            with self.subTest(stamp=stamp):
                with self.assertRaises(mod.ReceiptProtocolError):
                    verify(payload(accepted_at=stamp))

    def test_bool_sequence_is_not_integer(self):
        with self.assertRaises(mod.ReceiptProtocolError):
            verify(expected_node_sequence=True)

    def test_trusted_replay_ledger_is_mandatory(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "replay_ledger_required"):
            verify(seen_receipt_ids=None)

    def test_replayed_receipt_id_cannot_prune(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "already_processed"):
            verify(seen_receipt_ids={RECEIPT})

    def test_stale_receipt_cannot_prune_even_when_event_is_pending(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "stale_receipt"):
            verify(now=datetime(2026, 10, 24, 12, 2, tzinfo=timezone.utc))

    def test_future_dated_receipt_cannot_prune(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "future_receipt"):
            verify(now=datetime(2026, 10, 16, 11, 50, tzinfo=timezone.utc))

    def test_untrusted_naive_clock_blocks(self):
        with self.assertRaisesRegex(mod.ReceiptProtocolError, "invalid_trusted_clock"):
            verify(now=datetime(2026, 10, 16, 12, 2))

    def test_legacy_unscoped_topic_is_not_accepted(self):
        with self.assertRaises(mod.ReceiptProtocolError):
            verify(topic="nexolab/telemetry")


if __name__ == "__main__":
    unittest.main()
