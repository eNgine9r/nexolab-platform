from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.sessions.audit_contract import (
    canonical_audit_action,
    raw_actions_for_canonical,
)
from app.sessions.audit_schemas import SessionNoteCreate
from app.sessions.configuration import ConfiguredSessionRepository
from app.sessions.domain import SessionState
from app.sessions.models import (
    AuditLog,
    SessionEvent,
    SessionNote,
    SessionStage,
    TestSession,
)
from app.sessions.repository import (
    SessionConflictError,
    SessionNotFoundError,
    TransitionResult,
)
from app.sessions.schemas import SessionCreate


@dataclass(frozen=True, slots=True)
class SessionNoteResult:
    note: SessionNote
    event: SessionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class SessionNotesResult:
    items: list[SessionNote]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class AuditEntryView:
    id: str
    session_id: str | None
    session_event_id: str | None
    actor_id: str
    actor_source: str
    action: str
    canonical_action: str
    entity_type: str
    entity_id: str
    payload: dict[str, object]
    occurred_at: datetime
    inserted_at: datetime

    @classmethod
    def from_record(cls, record: AuditLog) -> "AuditEntryView":
        return cls(
            id=record.id,
            session_id=record.session_id,
            session_event_id=record.session_event_id,
            actor_id=record.actor_id,
            actor_source=record.actor_source,
            action=record.action,
            canonical_action=canonical_audit_action(record.action),
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            payload=record.payload,
            occurred_at=record.occurred_at,
            inserted_at=record.inserted_at,
        )


@dataclass(frozen=True, slots=True)
class AuditEntriesResult:
    items: list[AuditEntryView]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


class AuditedSessionRepository(ConfiguredSessionRepository):
    """Session repository with globally replayable create and audit notes."""

    def __init__(self, database: Database) -> None:
        super().__init__(database)

    def create(
        self,
        payload: SessionCreate,
        *,
        idempotency_key: str,
    ) -> TransitionResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    replay = self._create_event_by_key(db_session, normalized_key)
                    if replay is not None:
                        return self._replay_create(
                            db_session,
                            replay,
                            expected_session_number=payload.session_number,
                        )

                    duplicate_number = db_session.scalar(
                        select(TestSession.id).where(
                            TestSession.session_number == payload.session_number
                        )
                    )
                    if duplicate_number is not None:
                        raise SessionConflictError(
                            "session_number_conflict",
                            f"session number {payload.session_number!r} already exists",
                        )

                    now = datetime.now(UTC)
                    record = TestSession(
                        id=str(uuid4()),
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
                        session_id=record.id,
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
                    audit = self._audit_for_event(
                        event,
                        entity_type="test_session",
                    )

                    db_session.add(record)
                    db_session.flush()
                    db_session.add(event)
                    db_session.flush()
                    db_session.add(audit)
                    db_session.flush()

                db_session.expunge(record)
                db_session.expunge(event)
                return TransitionResult(
                    session=record,
                    event=event,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                replay = self._create_event_by_key(db_session, normalized_key)
                if replay is not None:
                    return self._replay_create(
                        db_session,
                        replay,
                        expected_session_number=payload.session_number,
                    )
                duplicate_number = db_session.scalar(
                    select(TestSession.id).where(
                        TestSession.session_number == payload.session_number
                    )
                )
                if duplicate_number is not None:
                    raise SessionConflictError(
                        "session_number_conflict",
                        f"session number {payload.session_number!r} already exists",
                    ) from error
                raise SessionConflictError(
                    "session_create_conflict",
                    "session could not be created because of a persistence conflict",
                ) from error

    def add_note(
        self,
        session_id: str,
        payload: SessionNoteCreate,
        *,
        idempotency_key: str,
    ) -> SessionNoteResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    record = self._locked_session(db_session, session_id)
                    existing = self._event_by_key(
                        db_session,
                        session_id,
                        normalized_key,
                    )
                    if existing is not None:
                        if existing.event_type != "note_added":
                            raise SessionConflictError(
                                "idempotency_key_reused",
                                "Idempotency-Key was used for another session command",
                            )
                        note_id = str(existing.payload.get("note_id", ""))
                        note = db_session.get(SessionNote, note_id)
                        if note is None:
                            raise SessionConflictError(
                                "note_replay_conflict",
                                "idempotent note result is no longer available",
                            )
                        db_session.expunge(note)
                        db_session.expunge(existing)
                        db_session.expunge(record)
                        return SessionNoteResult(
                            note=note,
                            event=existing,
                            replayed=True,
                        )

                    if payload.stage_id is not None:
                        stage = db_session.scalar(
                            select(SessionStage.id).where(
                                SessionStage.id == payload.stage_id,
                                SessionStage.session_id == session_id,
                            )
                        )
                        if stage is None:
                            raise SessionConflictError(
                                "session_stage_not_found",
                                "note stage does not belong to the session",
                            )

                    note = SessionNote(
                        id=str(uuid4()),
                        session_id=session_id,
                        stage_id=payload.stage_id,
                        author_id=payload.actor_id,
                        body=payload.body,
                        created_at=payload.occurred_at,
                    )
                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type="note_added",
                        previous_state=record.state,
                        next_state=record.state,
                        actor_id=payload.actor_id,
                        actor_source=payload.actor_source,
                        reason=payload.reason,
                        payload={
                            "note_id": note.id,
                            "stage_id": payload.stage_id,
                            "body_sha256": hashlib.sha256(
                                payload.body.encode("utf-8")
                            ).hexdigest(),
                        },
                        idempotency_key=normalized_key,
                        occurred_at=payload.occurred_at,
                        inserted_at=datetime.now(UTC),
                    )
                    audit = AuditLog(
                        id=str(uuid4()),
                        session_id=session_id,
                        session_event_id=event.id,
                        actor_id=event.actor_id,
                        actor_source=event.actor_source,
                        action=event.event_type,
                        entity_type="session_note",
                        entity_id=note.id,
                        payload=event.payload,
                        occurred_at=event.occurred_at,
                        inserted_at=event.inserted_at,
                    )

                    db_session.add(note)
                    db_session.flush()
                    db_session.add(event)
                    db_session.flush()
                    db_session.add(audit)
                    db_session.flush()

                db_session.expunge(note)
                db_session.expunge(event)
                return SessionNoteResult(
                    note=note,
                    event=event,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                existing = self._event_by_key(
                    db_session,
                    session_id,
                    normalized_key,
                )
                if existing is not None and existing.event_type == "note_added":
                    note_id = str(existing.payload.get("note_id", ""))
                    note = db_session.get(SessionNote, note_id)
                    if note is not None:
                        db_session.expunge(note)
                        db_session.expunge(existing)
                        return SessionNoteResult(
                            note=note,
                            event=existing,
                            replayed=True,
                        )
                raise SessionConflictError(
                    "note_create_conflict",
                    "note creation conflicted with another committed command",
                ) from error

    def notes(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> SessionNotesResult:
        with Session(self._engine, expire_on_commit=False) as db_session:
            if db_session.get(TestSession, session_id) is None:
                raise SessionNotFoundError(session_id)
            count = int(
                db_session.scalar(
                    select(func.count())
                    .select_from(SessionNote)
                    .where(SessionNote.session_id == session_id)
                )
                or 0
            )
            items = list(
                db_session.scalars(
                    select(SessionNote)
                    .where(SessionNote.session_id == session_id)
                    .order_by(
                        SessionNote.created_at.asc(),
                        SessionNote.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            for item in items:
                db_session.expunge(item)
        return SessionNotesResult(
            items=items,
            count=count,
            limit=limit,
            offset=offset,
        )

    def audit_entries(
        self,
        session_id: str,
        *,
        canonical_action: str | None,
        actor_id: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
        limit: int,
        offset: int,
    ) -> AuditEntriesResult:
        filters = [AuditLog.session_id == session_id]
        if canonical_action is not None:
            filters.append(
                AuditLog.action.in_(raw_actions_for_canonical(canonical_action))
            )
        if actor_id is not None:
            filters.append(AuditLog.actor_id == actor_id)
        if from_at is not None:
            filters.append(AuditLog.occurred_at >= from_at)
        if to_at is not None:
            filters.append(AuditLog.occurred_at < to_at)

        with Session(self._engine, expire_on_commit=False) as db_session:
            if db_session.get(TestSession, session_id) is None:
                raise SessionNotFoundError(session_id)
            count = int(
                db_session.scalar(
                    select(func.count()).select_from(AuditLog).where(*filters)
                )
                or 0
            )
            records = list(
                db_session.scalars(
                    select(AuditLog)
                    .where(*filters)
                    .order_by(
                        AuditLog.occurred_at.asc(),
                        AuditLog.inserted_at.asc(),
                        AuditLog.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            items = [AuditEntryView.from_record(record) for record in records]
        return AuditEntriesResult(
            items=items,
            count=count,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _create_event_by_key(
        db_session: Session,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent)
            .where(
                SessionEvent.event_type == "session_created",
                SessionEvent.idempotency_key == idempotency_key,
            )
            .order_by(SessionEvent.inserted_at.asc(), SessionEvent.id.asc())
            .limit(1)
        )

    @staticmethod
    def _replay_create(
        db_session: Session,
        event: SessionEvent,
        *,
        expected_session_number: str,
    ) -> TransitionResult:
        actual_session_number = str(event.payload.get("session_number", ""))
        if actual_session_number != expected_session_number:
            raise SessionConflictError(
                "idempotency_key_reused",
                "Idempotency-Key was used to create a different session",
            )
        record = db_session.get(TestSession, event.session_id)
        if record is None:
            raise SessionConflictError(
                "session_create_replay_conflict",
                "idempotent session result is no longer available",
            )
        db_session.expunge(record)
        db_session.expunge(event)
        return TransitionResult(session=record, event=event, replayed=True)
