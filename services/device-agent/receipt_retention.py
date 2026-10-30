"""Source-only, opt-in atomic PostgreSQL-committed receipt ledger for Edge SQLite.

This class is NOT wired to the production DeviceAgent or MQTT callbacks.
The trusted publisher authorization argument must originate from separately
verified broker identity/ACL, NEVER from the untrusted receipt body/topic.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from durable_receipt_v1 import (
    MAX_RECEIPT_BYTES,
    ReceiptProtocolError,
    validate_for_pending,
)
from main import OfflineQueue


def _strict_local_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptProtocolError("duplicate_local_pending_json_key")
        result[key] = value
    return result


class CommittedReceiptQueue(OfflineQueue):
    """Standalone Edge outbox receipt applier. Inherits legacy queue unchanged.

    The eventual caller must use this only with strict organization/node
    configuration and a broker-enforced central receipt publisher identity.
    It cannot be safely activated by a configuration flag alone.
    """

    def apply_committed_receipt(
        self,
        payload: bytes,
        *,
        topic: str,
        organization_id: str,
        node_id: str,
        central_publisher_authorized: bool = False,
        now: datetime | None = None,
    ) -> str:
        if central_publisher_authorized is not True:
            raise ReceiptProtocolError("central_publisher_not_authenticated")
        if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_RECEIPT_BYTES:
            raise ReceiptProtocolError("invalid_receipt_size")
        # This JSON lookup is ONLY a bounded index hint, not authentication or
        # validation. The strict shared contract re-parses and rejects duplicate
        # keys, identity drift, stale timestamps, and out-of-order final ACKs.
        try:
            hinted = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReceiptProtocolError("invalid_receipt_json") from exc
        receipt_id_hint = hinted.get("receipt_id") if isinstance(hinted, dict) else None
        if not isinstance(receipt_id_hint, str):
            receipt_id_hint = ""
        telemetry_topic = f"nexolab/v1/{organization_id}/{node_id}/telemetry"

        def operation() -> str:
            with self._connection:
                # Important: lock before re-reading oldest row and replay ledger.
                # The receipt ID insert and exactly one FIFO deletion commit
                # atomically, or are rolled back on *any* exception.
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS committed_receipt_ledger (
                        receipt_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        organization_id TEXT NOT NULL,
                        node_id TEXT NOT NULL,
                        committed_at TEXT NOT NULL
                    )
                    """
                )
                seen = self._connection.execute(
                    "SELECT receipt_id FROM committed_receipt_ledger WHERE receipt_id=?",
                    (receipt_id_hint,),
                ).fetchone()
                if seen is not None:
                    raise ReceiptProtocolError("receipt_id_already_processed")
                row = self._connection.execute(
                    """
                    SELECT id, event_id, payload
                    FROM outbound_queue
                    WHERE topic=?
                    ORDER BY id
                    LIMIT 1
                    """,
                    (telemetry_topic,),
                ).fetchone()
                if row is None:
                    raise ReceiptProtocolError("no_matching_pending_telemetry")
                try:
                    trusted_payload = json.loads(
                        str(row[2]), object_pairs_hook=_strict_local_pairs
                    )
                except (ValueError, TypeError) as exc:
                    raise ReceiptProtocolError("invalid_local_pending_payload") from exc
                if not isinstance(trusted_payload, dict):
                    raise ReceiptProtocolError("invalid_local_pending_payload")
                # The local SQLite column, its immutable payload and the
                # trusted node configuration MUST agree before acknowledging
                # or pruning. Reject corrupt local rows fail-closed.
                if (
                    trusted_payload.get("event_id") != row[1]
                    or trusted_payload.get("node_id") != node_id
                    or (
                        "organization_id" in trusted_payload
                        and trusted_payload["organization_id"] != organization_id
                    )
                    or (
                        "stream" in trusted_payload
                        and trusted_payload["stream"] != "telemetry"
                    )
                ):
                    raise ReceiptProtocolError("local_pending_identity_mismatch")
                sequence = trusted_payload.get("node_sequence")
                if type(sequence) is not int or sequence < 1:
                    raise ReceiptProtocolError("invalid_local_pending_sequence")

                decision = validate_for_pending(
                    payload,
                    topic=topic,
                    central_publisher_authorized=central_publisher_authorized,
                    expected_event_id=str(row[1]),
                    expected_organization_id=organization_id,
                    expected_node_id=node_id,
                    expected_node_sequence=sequence,
                    oldest_pending_sequence=sequence,
                    seen_receipt_ids=set(),
                    now=now,
                )
                # Both informational and final receipts get durable replay
                # protection. Informational acceptance never deletes a row.
                parsed = json.loads(payload)
                self._connection.execute(
                    """
                    INSERT INTO committed_receipt_ledger
                        (receipt_id, event_id, organization_id, node_id, committed_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        parsed["receipt_id"],
                        str(row[1]),
                        organization_id,
                        node_id,
                        parsed["accepted_at"],
                    ),
                )
                if decision == "prune_allowed":
                    removed = self._connection.execute(
                        "DELETE FROM outbound_queue WHERE id=? AND event_id=?",
                        (int(row[0]), str(row[1])),
                    )
                    if removed.rowcount != 1:
                        raise ReceiptProtocolError("pending_row_changed_during_commit")
                return decision

        with self._lock:
            return str(self._retry_busy("apply_committed_receipt", operation))
