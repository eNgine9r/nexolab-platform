from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.sessions.domain import (
    SessionAction,
    SessionDomainError,
    SessionState,
    TransitionCommand,
    session_configuration_is_mutable,
    transition_session,
)
from app.sessions.models import AuditLog, SessionEvent, TestSession
from app.sessions.schemas import (
    SessionCreate,
    SessionPatch,
    SessionTransitionRequest,
)


class SessionRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SessionNotFoundError(SessionRepositoryError):
    def __init__(self, session_id: str) -> None:
        super().__init__("session_not_found", f"session {session_id!r} was not found")
        self.session_id = session_id


class SessionConflictError(SessionRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class SessionPageResult:
    items: list[TestSession]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class SessionEventsResult:
    items: list[SessionEvent]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class TransitionResult:
    session: TestSession
    event: SessionEvent
    replayed: bool


class SessionRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def create(
        self,
        payload: SessionCreate,
        *,
        idempotency_key: str,
    ) -> TransitionResult:
        now = datetime.now(UTC)
        session_id = str(uuid4())
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        record = TestSession(
            id=session_id,
            session_number=payload.session_number,
            node_id=payload.node_id,
            state=SessionState.DRAFT.value,
            title=payload.title,
            customer=payload.customer,
            test_object=payload.test_object,
            model=payload.model,
            serial_number=payload.serial_number,
            standard=payload.standard,
            method=payload.method,
            operator_id=payload.operator_id,
            responsible_engineer_id=payload.responsible_engineer_id,
            metadata_payload=payload.metadata_payload,
            lock_version=1,
            created_at=now,
            updated_at=now,
        )
        event = SessionEvent(
            id=str(uuid4()),
            session_id=session_id,
            event_type="session_created",
            previous_state=None,
            next_state=SessionState.DRAFT.value,
            actor_id=payload.actor_id,
            actor_source="dashboard",
            reason=None,
            payload={"session_number": payload.session_number},
            idempotency_key=normalized_key,
            occurred_at=now,
            inserted_at=now,
        )
        audit = self._audit_for_event(event, entity_type="test_session")

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                db_session.add_all([record, event, audit])
                db_session.commit()
            except IntegrityError as error:
                db_session.rollback()
                existing = db_session.scalar(
                    select(TestSession).where(
                        TestSession.session_number == payload.session_number
                    )
                )
                if existing is not None:
                    raise SessionConflictError(
                        "session_number_conflict",
                        f"session number {payload.session_number!r} already exists",
                    ) from error
                raise SessionConflictError(
                    "session_create_conflict",
                    "session could not be created because of a persistence conflict",
                ) from error

        return TransitionResult(session=record, event=event, replayed=False)

    def get(self, session_id: str) -> TestSession:
        with Session(self._engine, expire_on_commit=False) as db_session:
            record = db_session.get(TestSession, session_id)
            if record is None:
                raise SessionNotFoundError(session_id)
            db_session.expunge(record)
            return record

    def list(
        self,
        *,
        state: SessionState | None,
        node_id: str | None,
        limit: int,
        offset: int,
    ) -> SessionPageResult:
        filters = []
        if state is not None:
            filters.append(TestSession.state == state.value)
        if node_id is not None:
            filters.append(TestSession.node_id == node_id)

        with Session(self._engine, expire_on_commit=False) as db_session:
            count_statement = select(func.count()).select_from(TestSession)
            statement = select(TestSession)
            if filters:
                count_statement = count_statement.where(*filters)
                statement = statement.where(*filters)

            count = int(db_session.scalar(count_statement) or 0)
            items = list(
                db_session.scalars(
                    statement.order_by(
                        TestSession.created_at.desc(), TestSession.id.desc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            for item in items:
                db_session.expunge(item)

        return SessionPageResult(
            items=items,
            count=count,
            limit=limit,
            offset=offset,
        )

    def patch(self, session_id: str, payload: SessionPatch) -> TestSession:
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self.get(session_id)

        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                record = db_session.scalar(
                    select(TestSession)
                    .where(TestSession.id == session_id)
                    .with_for_update()
                )
                if record is None:
                    raise SessionNotFoundError(session_id)

                state = SessionState(record.state)
                if not session_configuration_is_mutable(state):
                    raise SessionDomainError(
                        "session_immutable"
                        if state
                        in {
                            SessionState.COMPLETED,
                            SessionState.CANCELLED,
                            SessionState.ARCHIVED,
                        }
                        else "session_configuration_locked",
                        f"session configuration cannot be edited in {state.value} state",
                        current_state=state,
                    )

                for field, value in changes.items():
                    setattr(record, field, value)
                record.lock_version += 1
                record.updated_at = datetime.now(UTC)

            db_session.expunge(record)
            return record

    def transition(
        self,
        session_id: str,
        action: SessionAction,
        request: SessionTransitionRequest,
        *,
        idempotency_key: str,
    ) -> TransitionResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    record = db_session.scalar(
                        select(TestSession)
                        .where(TestSession.id == session_id)
                        .with_for_update()
                    )
                    if record is None:
                        raise SessionNotFoundError(session_id)

                    existing = db_session.scalar(
                        select(SessionEvent).where(
                            SessionEvent.session_id == session_id,
                            SessionEvent.idempotency_key == normalized_key,
                        )
                    )
                    if existing is not None:
                        db_session.expunge(existing)
                        db_session.expunge(record)
                        return TransitionResult(
                            session=record,
                            event=existing,
                            replayed=True,
                        )

                    command = TransitionCommand(
                        idempotency_key=normalized_key,
                        actor_id=request.actor_id,
                        occurred_at=request.occurred_at,
                        reason=request.reason,
                    )
                    transition = transition_session(
                        SessionState(record.state),
                        action,
                        command,
                    )
                    now = datetime.now(UTC)
                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type=transition.event_type,
                        previous_state=transition.previous_state.value,
                        next_state=transition.next_state.value,
                        actor_id=request.actor_id,
                        actor_source=request.actor_source,
                        reason=request.reason,
                        payload={"action": action.value},
                        idempotency_key=normalized_key,
                        occurred_at=request.occurred_at,
                        inserted_at=now,
                    )

                    record.state = transition.next_state.value
                    record.lock_version += 1
                    record.updated_at = now
                    self._apply_transition_timestamp(
                        record,
                        action=action,
                        occurred_at=request.occurred_at,
                    )
                    db_session.add(event)
                    db_session.add(
                        self._audit_for_event(event, entity_type="test_session")
                    )
                    db_session.flush()

                db_session.expunge(event)
                db_session.expunge(record)
                return TransitionResult(
                    session=record,
                    event=event,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                existing = db_session.scalar(
                    select(SessionEvent).where(
                        SessionEvent.session_id == session_id,
                        SessionEvent.idempotency_key == normalized_key,
                    )
                )
                record = db_session.get(TestSession, session_id)
                if existing is not None and record is not None:
                    db_session.expunge(existing)
                    db_session.expunge(record)
                    return TransitionResult(
                        session=record,
                        event=existing,
                        replayed=True,
                    )
                raise SessionConflictError(
                    "session_transition_conflict",
                    "session transition conflicted with another committed change",
                ) from error

    def events(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> SessionEventsResult:
        with Session(self._engine, expire_on_commit=False) as db_session:
            if db_session.get(TestSession, session_id) is None:
                raise SessionNotFoundError(session_id)

            count = int(
                db_session.scalar(
                    select(func.count())
                    .select_from(SessionEvent)
                    .where(SessionEvent.session_id == session_id)
                )
                or 0
            )
            items = list(
                db_session.scalars(
                    select(SessionEvent)
                    .where(SessionEvent.session_id == session_id)
                    .order_by(
                        SessionEvent.occurred_at.asc(),
                        SessionEvent.inserted_at.asc(),
                        SessionEvent.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            for item in items:
                db_session.expunge(item)

        return SessionEventsResult(
            items=items,
            count=count,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _normalize_idempotency_key(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise SessionRepositoryError(
                "invalid_idempotency_key",
                "Idempotency-Key must not be empty",
            )
        if len(normalized) > 128:
            raise SessionRepositoryError(
                "invalid_idempotency_key",
                "Idempotency-Key must not exceed 128 characters",
            )
        return normalized

    @staticmethod
    def _apply_transition_timestamp(
        record: TestSession,
        *,
        action: SessionAction,
        occurred_at: datetime,
    ) -> None:
        if action is SessionAction.PREPARE:
            record.prepared_at = occurred_at
        elif action is SessionAction.START:
            record.started_at = occurred_at
        elif action is SessionAction.PAUSE:
            record.paused_at = occurred_at
        elif action is SessionAction.RESUME:
            record.paused_at = None
        elif action is SessionAction.COMPLETE:
            record.completed_at = occurred_at
        elif action is SessionAction.CANCEL:
            record.cancelled_at = occurred_at
        elif action is SessionAction.ARCHIVE:
            record.archived_at = occurred_at

    @staticmethod
    def _audit_for_event(
        event: SessionEvent,
        *,
        entity_type: str,
    ) -> AuditLog:
        return AuditLog(
            id=str(uuid4()),
            session_id=event.session_id,
            session_event_id=event.id,
            actor_id=event.actor_id,
            actor_source=event.actor_source,
            action=event.event_type,
            entity_type=entity_type,
            entity_id=event.session_id,
            payload={
                "previous_state": event.previous_state,
                "next_state": event.next_state,
            },
            occurred_at=event.occurred_at,
            inserted_at=event.inserted_at,
        )
