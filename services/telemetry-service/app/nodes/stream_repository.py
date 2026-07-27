from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.domain import (
    NodeState,
    NodeTopicStream,
    classify_clock_offset,
    parse_node_topic,
)
from app.nodes.models import (
    CentralNode,
    CentralNodeCredential,
    CentralNodeHealthSample,
    CentralNodeIngressCursor,
    CentralNodeStatusEvent,
)
from app.nodes.stream_contracts import NodeHealthEvent, NodeStatusEvent, NodeStreamEvent


class NodeStreamRepositoryError(RuntimeError):
    code = "node_stream_repository_error"


class NodeStreamAuthorizationError(NodeStreamRepositoryError):
    code = "node_stream_authorization_failed"


class NodeStreamReplayError(NodeStreamRepositoryError):
    code = "node_stream_replay"


class NodeStreamConflictError(NodeStreamRepositoryError):
    code = "node_stream_conflict"


class NodeStreamRepository:
    def __init__(self, database: Database, *, organization_id: str | None = None) -> None:
        self._engine = database.engine
        self._organization_id = organization_id

    def for_organization(self, organization_id: str) -> "NodeStreamRepository":
        normalized = organization_id.strip()
        if not normalized:
            raise ValueError("organization_id is required")
        return NodeStreamRepository(
            _DatabaseEngineAdapter(self._engine),
            organization_id=normalized,
        )

    def persist_health(
        self,
        event: NodeHealthEvent,
        *,
        topic: str,
        received_at: datetime,
    ) -> tuple[CentralNodeHealthSample, bool]:
        received = _aware_utc(received_at)
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    node, replayed = self._authorize_and_advance(
                        session,
                        event=event,
                        topic=topic,
                        expected_stream=NodeTopicStream.HEALTH,
                        received_at=received,
                    )
                    existing = self._health_by_event(session, str(event.event_id))
                    if replayed:
                        if existing is None:
                            raise NodeStreamConflictError(
                                "health cursor replay references a missing history event"
                            )
                        session.expunge(existing)
                        session.expunge(node)
                        return existing, True
                    if existing is not None:
                        raise NodeStreamConflictError("health event_id is already persisted")
                    row = CentralNodeHealthSample(
                        id=str(uuid4()),
                        organization_id=node.organization_id,
                        node_record_id=node.id,
                        event_id=str(event.event_id),
                        node_sequence=event.node_sequence,
                        health=event.health,
                        uptime_seconds=event.uptime_seconds,
                        queue_depth=event.queue_depth,
                        samples_total=event.samples_total,
                        software_version=event.software_version,
                        device_mode=event.device_mode,
                        last_sample_at=event.last_sample_at,
                        last_publish_at=event.last_publish_at,
                        last_error=event.last_error,
                        captured_at=event.captured_at,
                        received_at=received,
                    )
                    session.add(row)
                    session.flush()
            except IntegrityError as error:
                raise NodeStreamConflictError(
                    "health event conflicts with persisted stream history"
                ) from error
            session.expunge(row)
            session.expunge(node)
            return row, False

    def persist_status(
        self,
        event: NodeStatusEvent,
        *,
        topic: str,
        received_at: datetime,
    ) -> tuple[CentralNodeStatusEvent, bool]:
        received = _aware_utc(received_at)
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                with session.begin():
                    node, replayed = self._authorize_and_advance(
                        session,
                        event=event,
                        topic=topic,
                        expected_stream=NodeTopicStream.STATUS,
                        received_at=received,
                    )
                    existing = self._status_by_event(session, str(event.event_id))
                    if replayed:
                        if existing is None:
                            raise NodeStreamConflictError(
                                "status cursor replay references a missing history event"
                            )
                        session.expunge(existing)
                        session.expunge(node)
                        return existing, True
                    if existing is not None:
                        raise NodeStreamConflictError("status event_id is already persisted")
                    row = CentralNodeStatusEvent(
                        id=str(uuid4()),
                        organization_id=node.organization_id,
                        node_record_id=node.id,
                        event_id=str(event.event_id),
                        node_sequence=event.node_sequence,
                        status=event.status,
                        reason=event.reason,
                        software_version=event.software_version,
                        graceful=event.graceful,
                        captured_at=event.captured_at,
                        received_at=received,
                    )
                    session.add(row)
                    session.flush()
            except IntegrityError as error:
                raise NodeStreamConflictError(
                    "status event conflicts with persisted stream history"
                ) from error
            session.expunge(row)
            session.expunge(node)
            return row, False

    def latest_health(self, node_id: str) -> CentralNodeHealthSample | None:
        with Session(self._engine, expire_on_commit=False) as session:
            node = self._node(session, node_id)
            row = session.scalar(
                select(CentralNodeHealthSample)
                .where(CentralNodeHealthSample.node_record_id == node.id)
                .order_by(
                    CentralNodeHealthSample.captured_at.desc(),
                    CentralNodeHealthSample.node_sequence.desc(),
                )
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row

    def latest_status(self, node_id: str) -> CentralNodeStatusEvent | None:
        with Session(self._engine, expire_on_commit=False) as session:
            node = self._node(session, node_id)
            row = session.scalar(
                select(CentralNodeStatusEvent)
                .where(CentralNodeStatusEvent.node_record_id == node.id)
                .order_by(
                    CentralNodeStatusEvent.captured_at.desc(),
                    CentralNodeStatusEvent.node_sequence.desc(),
                )
                .limit(1)
            )
            if row is not None:
                session.expunge(row)
            return row

    def health_history(self, node_id: str, *, limit: int = 100) -> list[CentralNodeHealthSample]:
        return self._history(
            node_id,
            select(CentralNodeHealthSample).order_by(
                CentralNodeHealthSample.captured_at.desc(),
                CentralNodeHealthSample.node_sequence.desc(),
            ),
            CentralNodeHealthSample,
            limit=limit,
        )

    def status_history(self, node_id: str, *, limit: int = 100) -> list[CentralNodeStatusEvent]:
        return self._history(
            node_id,
            select(CentralNodeStatusEvent).order_by(
                CentralNodeStatusEvent.captured_at.desc(),
                CentralNodeStatusEvent.node_sequence.desc(),
            ),
            CentralNodeStatusEvent,
            limit=limit,
        )

    def _history(
        self,
        node_id: str,
        statement: Select[tuple[object]],
        model: type[CentralNodeHealthSample] | type[CentralNodeStatusEvent],
        *,
        limit: int,
    ) -> list[CentralNodeHealthSample] | list[CentralNodeStatusEvent]:
        bounded = max(1, min(limit, 1000))
        with Session(self._engine, expire_on_commit=False) as session:
            node = self._node(session, node_id)
            rows = list(
                session.scalars(
                    statement.where(model.node_record_id == node.id).limit(bounded)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def _authorize_and_advance(
        self,
        session: Session,
        *,
        event: NodeStreamEvent,
        topic: str,
        expected_stream: NodeTopicStream,
        received_at: datetime,
    ) -> tuple[CentralNode, bool]:
        parsed = parse_node_topic(topic)
        if parsed.stream is not expected_stream:
            raise NodeStreamAuthorizationError(
                f"expected {expected_stream.value} stream, received {parsed.stream.value}"
            )
        if parsed.organization_id != self._scope() or parsed.node_id != event.node_id:
            raise NodeStreamAuthorizationError(
                "payload identity does not own the MQTT topic"
            )
        node = session.scalar(
            select(CentralNode)
            .where(
                CentralNode.organization_id == self._scope(),
                CentralNode.node_id == event.node_id,
            )
            .with_for_update()
        )
        if node is None or NodeState(node.state) is not NodeState.ACTIVE:
            raise NodeStreamAuthorizationError("node is unknown or not active")
        credential = session.scalar(
            select(CentralNodeCredential.id)
            .where(
                CentralNodeCredential.organization_id == self._scope(),
                CentralNodeCredential.node_record_id == node.id,
                CentralNodeCredential.revoked_at.is_(None),
            )
            .order_by(CentralNodeCredential.generation.desc())
            .limit(1)
        )
        if credential is None:
            raise NodeStreamAuthorizationError("node has no active broker credential")

        cursor = session.scalar(
            select(CentralNodeIngressCursor)
            .where(
                CentralNodeIngressCursor.node_record_id == node.id,
                CentralNodeIngressCursor.stream == expected_stream.value,
            )
            .with_for_update()
        )
        replayed = False
        if cursor is None:
            cursor = CentralNodeIngressCursor(
                id=str(uuid4()),
                organization_id=self._scope(),
                node_record_id=node.id,
                stream=expected_stream.value,
                last_sequence=event.node_sequence,
                last_event_id=str(event.event_id),
                last_captured_at=event.captured_at,
                updated_at=received_at,
            )
            session.add(cursor)
        elif event.node_sequence < cursor.last_sequence:
            raise NodeStreamReplayError(
                "node_sequence is lower than the persisted stream cursor"
            )
        elif event.node_sequence == cursor.last_sequence:
            if str(event.event_id) != cursor.last_event_id:
                raise NodeStreamReplayError(
                    "node_sequence is already bound to another event"
                )
            replayed = True
        else:
            cursor.last_sequence = event.node_sequence
            cursor.last_event_id = str(event.event_id)
            cursor.last_captured_at = event.captured_at
            cursor.updated_at = received_at

        offset_ms = round((event.captured_at - received_at).total_seconds() * 1000)
        node.last_seen_at = received_at
        node.last_clock_offset_ms = offset_ms
        node.clock_status = classify_clock_offset(
            offset_ms,
            warning_ms=node.clock_warning_ms,
            critical_ms=node.clock_critical_ms,
        ).value
        node.clock_observed_at = received_at
        node.updated_at = received_at
        session.flush()
        return node, replayed

    def _node(self, session: Session, node_id: str) -> CentralNode:
        row = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == self._scope(),
                CentralNode.node_id == node_id.strip().lower(),
            )
        )
        if row is None:
            raise NodeStreamAuthorizationError("node was not found")
        return row

    def _health_by_event(
        self,
        session: Session,
        event_id: str,
    ) -> CentralNodeHealthSample | None:
        return session.scalar(
            select(CentralNodeHealthSample).where(
                CentralNodeHealthSample.organization_id == self._scope(),
                CentralNodeHealthSample.event_id == event_id,
            )
        )

    def _status_by_event(
        self,
        session: Session,
        event_id: str,
    ) -> CentralNodeStatusEvent | None:
        return session.scalar(
            select(CentralNodeStatusEvent).where(
                CentralNodeStatusEvent.organization_id == self._scope(),
                CentralNodeStatusEvent.event_id == event_id,
            )
        )

    def _scope(self) -> str:
        if self._organization_id is None:
            raise NodeStreamRepositoryError("organization scope is required")
        return self._organization_id


class _DatabaseEngineAdapter:
    """Minimal Database-compatible adapter for scoped repository clones."""

    def __init__(self, engine: object) -> None:
        self.engine = engine


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    return value.astimezone(UTC)
