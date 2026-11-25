"""Source-only, opt-in atomic PostgreSQL-committed receipt ledger for Edge SQLite.

This class is NOT wired to the production DeviceAgent or MQTT callbacks.
The trusted publisher authorization argument must originate from separately
verified broker identity/ACL, NEVER from the untrusted receipt body/topic.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timezone
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

    def delete(self, record_id: int) -> None:
        """Never allow legacy MQTT PUBACK code to prune a receipt-mode row.

        A future device-agent mode switch must implement correct QoS1 replay
        without calling this method. Direct deletion bypasses final durable
        PostgreSQL acknowledgement and is forbidden for this queue class.
        """
        raise ReceiptProtocolError("postgres_committed_receipt_required")

    def oldest_receipt_replay_candidate(self) -> tuple[int, str, str, str] | None:
        """Read the oldest immutable SQLite event without modifying it.

        Unlike the legacy PUBACK queue loop this preserves the column event_id
        so a replay caller can fail closed if the JSON payload was corrupted.
        Never skip a foreign/legacy row to bypass strict FIFO ordering.
        """

        def operation() -> tuple[int, str, str, str] | None:
            row = self._connection.execute(
                """
                SELECT id, event_id, topic, payload
                FROM outbound_queue ORDER BY id LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            return int(row[0]), str(row[1]), str(row[2]), str(row[3])

        with self._lock:
            return self._retry_busy("oldest_receipt_replay_candidate", operation)

    def replay_capacity_snapshot(self, *, now: datetime | None = None) -> dict[str, object]:
        """Read-only, bounded local queue/disk indicators; not a retention guarantee.

        No credentials, raw payloads or site paths are returned. The metric
        cannot establish complete site backup, disk endurance or network ACK.
        """
        clock = datetime.now(timezone.utc) if now is None else now
        if clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("timezone_aware_clock_required")

        def operation() -> tuple[int, int, str | None]:
            row = self._connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(LENGTH(CAST(payload AS BLOB))), 0),
                       (SELECT created_at FROM outbound_queue ORDER BY id LIMIT 1)
                FROM outbound_queue
                """
            ).fetchone()
            return int(row[0]), int(row[1]), row[2]

        with self._lock:
            count, payload_bytes, oldest_at = self._retry_busy(
                "replay_capacity_snapshot", operation
            )
        age_seconds: float | None = None
        timestamp_valid = True
        if oldest_at is not None:
            try:
                parsed = datetime.fromisoformat(oldest_at)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError("timezone_missing")
                age_seconds = max(0.0, (clock - parsed).total_seconds())
            except (TypeError, ValueError, OverflowError):
                timestamp_valid = False

        database_bytes = sum(
            candidate.stat().st_size if candidate.exists() else 0
            for candidate in (
                self._database_path,
                self._database_path.with_name(self._database_path.name + "-wal"),
                self._database_path.with_name(self._database_path.name + "-shm"),
            )
        )
        return {
            "schema_version": 1,
            "pending_count": count,
            "pending_payload_bytes": payload_bytes,
            "sqlite_file_bytes": database_bytes,
            "filesystem_free_bytes": shutil.disk_usage(self._database_path.parent).free,
            "oldest_pending_age_seconds": age_seconds,
            "oldest_timestamp_valid": timestamp_valid,
            "retention_guaranteed": False,
        }

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
                # Replay always selects the globally oldest row. Never
                # acknowledge a later scoped event while an older legacy,
                # foreign-tenant or other-stream row blocks actual publishing.
                # A topic-filtered query here would bypass that FIFO guard
                # and silently prune an event the Edge could not yet replay.
                row = self._connection.execute(
                    """
                    SELECT id, event_id, topic, payload
                    FROM outbound_queue
                    ORDER BY id
                    LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    raise ReceiptProtocolError("no_matching_pending_telemetry")
                if row[2] != telemetry_topic:
                    raise ReceiptProtocolError("oldest_pending_topic_not_scoped")
                try:
                    trusted_payload = json.loads(
                        str(row[3]), object_pairs_hook=_strict_local_pairs
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
