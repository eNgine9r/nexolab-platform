"""Opt-in identity contract for a PostgreSQL-committed telemetry receipt.

Never construct an identity directly from an untrusted MQTT payload.
The future caller must first verify broker authentication/ACL and node
registry ownership of the exact topic with NodeIngressAuthorizer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re
from typing import Any
from uuid import UUID

from app.contracts import TelemetryEvent


_NODE_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class CommittedReceiptIdentity:
    organization_id: str
    node_id: str
    node_sequence: int

    def __post_init__(self) -> None:
        try:
            canonical = str(UUID(self.organization_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("invalid_receipt_organization") from exc
        if self.organization_id != canonical:
            raise ValueError("noncanonical_receipt_organization")
        if not isinstance(self.node_id, str) or _NODE_ID.fullmatch(self.node_id) is None:
            raise ValueError("invalid_receipt_node")
        if type(self.node_sequence) is not int or self.node_sequence < 1:
            raise ValueError("invalid_receipt_sequence")

    @property
    def receipt_topic(self) -> str:
        return f"nexolab/v1/{self.organization_id}/{self.node_id}/receipts"

    def validate_raw(self, event: TelemetryEvent, raw: dict[str, Any]) -> None:
        if event.node_id != self.node_id or raw.get("node_id") != self.node_id:
            raise ValueError("receipt_node_mismatch")
        if raw.get("node_sequence") != self.node_sequence or type(raw.get("node_sequence")) is not int:
            raise ValueError("receipt_sequence_unverified")
        if "organization_id" in raw and raw["organization_id"] != self.organization_id:
            raise ValueError("receipt_organization_mismatch")


def prepare_committed_receipt(
    *,
    event_id: str,
    identity: CommittedReceiptIdentity,
    receipt_id: str,
) -> tuple[dict[str, Any], datetime]:
    """Build an immutable final-only intent. Publication occurs AFTER commit."""
    for field in (event_id, receipt_id):
        if str(UUID(field)) != field:
            raise ValueError("noncanonical_receipt_id")
    now = datetime.now(UTC)
    return (
        {
            "contract_version": 1,
            "receipt_id": receipt_id,
            "event_id": event_id,
            "organization_id": identity.organization_id,
            "node_id": identity.node_id,
            "stream": "telemetry",
            "node_sequence": identity.node_sequence,
            "receipt_level": "postgres_committed",
            "accepted_at": now.isoformat().replace("+00:00", "Z"),
        },
        now,
    )
