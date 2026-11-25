"""NEXOLAB durable receipt v1: pure, fail-closed protocol validation.

Contract-only (Issue #1410). Not wired to MQTT, SQLite deletion or the
production Device Agent. The local broker's *actual* publisher ACL must be
verified by a future integration before passing central_publisher_authorized.

Exact-row binding (#1762 slice 4). A final ``postgres_committed`` receipt may
prune ANY pending outbox row, not only the oldest, but only the one row whose
event_id, node_sequence, organization, node and exact org-scoped telemetry
topic all match the receipt. It never authorizes pruning a different, earlier
or later row. Unknown or already pruned rows are rejected by the caller's
outbox lookup before this call.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_RECEIPT_BYTES = 2048
FIELDS = frozenset((
    "contract_version", "receipt_id", "event_id", "organization_id",
    "node_id", "stream", "node_sequence", "receipt_level", "accepted_at",
))
NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
TOPIC_SUFFIX = "receipts"
LEVELS = frozenset(("durably_spooled", "postgres_committed"))


class ReceiptProtocolError(ValueError):
    """Untrusted, incomplete, mismatched, or non-prunable receipt."""


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReceiptProtocolError("duplicate_receipt_json_key")
        result[key] = value
    return result


def _uuid(raw: Any) -> str:
    if not isinstance(raw, str):
        raise ReceiptProtocolError("invalid_receipt_uuid")
    try:
        value = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ReceiptProtocolError("invalid_receipt_uuid") from exc
    if str(value) != raw:
        raise ReceiptProtocolError("noncanonical_receipt_uuid")
    return raw


def validate_for_pending(
    payload: bytes,
    *,
    topic: str,
    central_publisher_authorized: bool = False,
    expected_event_id: str,
    expected_organization_id: str,
    expected_node_id: str,
    expected_node_sequence: int,
    pending_row_topic: str,
    seen_receipt_ids: set[str] | frozenset[str] | None = None,
    now: datetime | None = None,
) -> str:
    """Return 'informational' or 'prune_allowed', otherwise raise.

    All expected_* arguments and pending_row_topic MUST come from trusted
    local node configuration and the ONE existing SQLite outbox record the
    receipt names (not from the MQTT payload). That record's stored topic must
    be exactly this node's org-scoped telemetry topic.
    The caller MUST verify central MQTT publisher ACL/auth separately.
    Replayed/deleted events are rejected by outbox lookup before this call.
    No storage mutation or network I/O occurs here.
    """
    if not isinstance(seen_receipt_ids, (set, frozenset)):
        raise ReceiptProtocolError("trusted_receipt_replay_ledger_required")
    if central_publisher_authorized is not True:
        raise ReceiptProtocolError("central_publisher_not_authenticated")
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_RECEIPT_BYTES:
        raise ReceiptProtocolError("invalid_receipt_size")
    _uuid(expected_event_id)
    _uuid(expected_organization_id)
    if not isinstance(expected_node_id, str) or not NODE_ID.fullmatch(expected_node_id):
        raise ReceiptProtocolError("invalid_expected_node_id")
    if type(expected_node_sequence) is not int or expected_node_sequence < 1:
        raise ReceiptProtocolError("invalid_pending_sequence")
    expected_topic = (
        f"nexolab/v1/{expected_organization_id}/"
        f"{expected_node_id}/{TOPIC_SUFFIX}"
    )
    if topic != expected_topic:
        raise ReceiptProtocolError("receipt_topic_identity_mismatch")
    # Exact-row binding: the pending row itself must be this node's scoped
    # telemetry. Legacy, foreign-tenant or other-stream rows are never pruned.
    if pending_row_topic != (
        f"nexolab/v1/{expected_organization_id}/{expected_node_id}/telemetry"
    ):
        raise ReceiptProtocolError("pending_row_topic_not_scoped")

    try:
        receipt = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReceiptProtocolError("invalid_receipt_json") from exc
    if not isinstance(receipt, dict) or set(receipt) != FIELDS:
        raise ReceiptProtocolError("invalid_receipt_fields")
    if type(receipt["contract_version"]) is not int or receipt["contract_version"] != 1:
        raise ReceiptProtocolError("unsupported_receipt_version")
    _uuid(receipt["receipt_id"])
    if receipt["receipt_id"] in seen_receipt_ids:
        raise ReceiptProtocolError("receipt_id_already_processed")
    _uuid(receipt["event_id"])
    _uuid(receipt["organization_id"])
    if (
        receipt["event_id"] != expected_event_id
        or receipt["organization_id"] != expected_organization_id
        or receipt["node_id"] != expected_node_id
        or receipt["stream"] != "telemetry"
    ):
        raise ReceiptProtocolError("receipt_identity_mismatch")
    if (
        type(receipt["node_sequence"]) is not int
        or receipt["node_sequence"] != expected_node_sequence
    ):
        raise ReceiptProtocolError("receipt_sequence_mismatch")
    level = receipt["receipt_level"]
    if not isinstance(level, str) or level not in LEVELS:
        raise ReceiptProtocolError("unsupported_durability_level")
    stamp = receipt["accepted_at"]
    if not isinstance(stamp, str) or len(stamp) > 40:
        raise ReceiptProtocolError("invalid_acceptance_timestamp")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptProtocolError("invalid_acceptance_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReceiptProtocolError("timestamp_missing_timezone")
    clock = datetime.now(timezone.utc) if now is None else now
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise ReceiptProtocolError("invalid_trusted_clock")
    if parsed > clock + timedelta(minutes=5):
        raise ReceiptProtocolError("future_receipt_timestamp")
    if parsed < clock - timedelta(days=7):
        raise ReceiptProtocolError("stale_receipt_timestamp")

    # Informational spool acceptance is NEVER a final SQLite deletion ACK.
    if receipt["receipt_level"] == "durably_spooled":
        return "informational"
    # Exact-row binding replaces the former FIFO-head rule: every identity
    # field above matched the one named pending row, so only it may be pruned.
    return "prune_allowed"
