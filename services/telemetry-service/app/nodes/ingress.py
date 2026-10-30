from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import TelemetryEvent
from app.committed_receipts import CommittedReceiptIdentity
from app.db import Database
from app.nodes.domain import (
    ClockStatus,
    NodeState,
    NodeTopicStream,
    classify_clock_offset,
    parse_node_topic,
)
from app.nodes.models import (
    CentralNode,
    CentralNodeCredential,
    CentralNodeIngressCursor,
)


NODE_AUTHORIZATION_REASON = "node_authorization"
NODE_REPLAY_REASON = "node_replay"


class NodeIngressAuthorizer:
    """Authorize telemetry after a trusted MQTT broker accepted the publisher.

    The broker owns password verification and ACL enforcement. This gate verifies
    the persisted registry state, exact topic ownership, payload identity and
    monotonic node sequence before telemetry reaches normalized storage.
    """

    def __init__(self, database: Database) -> None:
        self._engine = database.engine
        self._database = database

    def authorize(
        self,
        event: TelemetryEvent,
        topic: str | None,
        observed_at: datetime,
    ) -> tuple[bool, str, str]:
        """Legacy ingress authorization; no committed receipt is created."""
        allowed, reason, detail, _ = self._authorize(event, topic, observed_at)
        return allowed, reason, detail

    def authorize_and_persist_committed(
        self,
        event: TelemetryEvent,
        raw_payload: dict[str, Any],
        topic: str | None,
        observed_at: datetime,
    ) -> tuple[bool, str, str, bool | None]:
        """Atomic registry/cursor/sample/outbox path (not runtime-connected).

        Callers must independently prove MQTT broker authentication, per-node
        ingress ACL and source identity. Validated registry state alone is not
        proof of the broker's actual publishing principal.
        """
        if self._database.engine.dialect.name != "postgresql":
            raise RuntimeError("postgresql_required_for_committed_receipt")
        return self._authorize(event, topic, observed_at, raw_payload)

    def _authorize(
        self,
        event: TelemetryEvent,
        topic: str | None,
        observed_at: datetime,
        raw_payload: dict[str, Any] | None = None,
    ) -> tuple[bool, str, str, bool | None]:
        if topic is None:
            return False, NODE_AUTHORIZATION_REASON, "node-registry mode requires an MQTT topic", None
        try:
            parsed = parse_node_topic(topic)
        except ValueError as error:
            return False, NODE_AUTHORIZATION_REASON, str(error), None
        if parsed.stream is not NodeTopicStream.TELEMETRY:
            return False, NODE_AUTHORIZATION_REASON, "telemetry ingestion accepts only the telemetry stream", None
        if parsed.node_id != event.node_id.strip().lower():
            return False, NODE_AUTHORIZATION_REASON, "payload node_id does not match the owned MQTT topic", None

        sequence = _node_sequence(event)
        if sequence is None:
            return False, NODE_REPLAY_REASON, "node_sequence must be a positive integer in registry mode", None

        observed = _aware_utc(observed_at)
        node_time = event.captured_at.astimezone(UTC)
        event_id = str(event.event_id)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                node = session.scalar(
                    select(CentralNode)
                    .where(
                        CentralNode.organization_id == parsed.organization_id,
                        CentralNode.node_id == parsed.node_id,
                    )
                    .with_for_update()
                )
                if node is None or NodeState(node.state) is not NodeState.ACTIVE:
                    return False, NODE_AUTHORIZATION_REASON, "node is unknown or not active", None
                credential = session.scalar(
                    select(CentralNodeCredential.id)
                    .where(
                        CentralNodeCredential.organization_id == parsed.organization_id,
                        CentralNodeCredential.node_record_id == node.id,
                        CentralNodeCredential.revoked_at.is_(None),
                    )
                    .order_by(CentralNodeCredential.generation.desc())
                    .limit(1)
                )
                if credential is None:
                    return False, NODE_AUTHORIZATION_REASON, "node has no active broker credential", None

                cursor = session.scalar(
                    select(CentralNodeIngressCursor)
                    .where(
                        CentralNodeIngressCursor.node_record_id == node.id,
                        CentralNodeIngressCursor.stream == parsed.stream.value,
                    )
                    .with_for_update()
                )
                if cursor is None:
                    cursor = CentralNodeIngressCursor(
                        id=str(uuid4()),
                        organization_id=parsed.organization_id,
                        node_record_id=node.id,
                        stream=parsed.stream.value,
                        last_sequence=sequence,
                        last_event_id=event_id,
                        last_captured_at=node_time,
                        updated_at=observed,
                    )
                    session.add(cursor)
                elif sequence < cursor.last_sequence:
                    return False, NODE_REPLAY_REASON, "node_sequence is lower than the persisted cursor", None
                elif sequence == cursor.last_sequence:
                    if event_id != cursor.last_event_id:
                        return False, NODE_REPLAY_REASON, "node_sequence is already bound to another event", None
                else:
                    cursor.last_sequence = sequence
                    cursor.last_event_id = event_id
                    cursor.last_captured_at = node_time
                    cursor.updated_at = observed

                offset_ms = round((node_time - observed).total_seconds() * 1000)
                clock_status = classify_clock_offset(
                    offset_ms,
                    warning_ms=node.clock_warning_ms,
                    critical_ms=node.clock_critical_ms,
                )
                node.last_seen_at = observed
                node.last_clock_offset_ms = offset_ms
                node.clock_status = clock_status.value
                node.clock_observed_at = observed
                node.updated_at = observed
                session.flush()
                inserted: bool | None = None
                if raw_payload is not None:
                    # Use EXACTLY the authorization/cursor transaction; a failed
                    # telemetry commit cannot advance the node's high-water mark.
                    inserted = self._database.persist(
                        event,
                        raw_payload,
                        receipt_identity=CommittedReceiptIdentity(
                            parsed.organization_id, parsed.node_id, sequence
                        ),
                        connection=session.connection(),
                    )
        return True, "authorized", ClockStatus(clock_status).value, inserted


def _node_sequence(event: TelemetryEvent) -> int | None:
    value = (event.model_extra or {}).get("node_sequence")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC)
