from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.sessions.audit_schemas import SessionNoteCreate, StageAdvanceRequest
from app.sessions.configuration import ConfiguredSessionRepository
from app.sessions.domain import (
    SessionAction,
    SessionState,
    validate_stage_transition,
)
from app.sessions.models import (
    AuditLog,
    SessionEvent,
    SessionNote,
    SessionStage,
    SessionStageTransition,
    TestSession,
)
from app.sessions.repository import (
    SessionConflictError,
    SessionEventsResult,
    TransitionResult,
)
from app.sessions.schemas import SessionCreate, SessionTransitionRequest


_ACTION_EVENT_TYPES: dict[SessionAction, str] = {
    SessionAction.PREPARE: "session_prepared",
    SessionAction.START: "session_started",
    SessionAction.PAUSE: "session_paused",
    SessionAction.RESUME: "session_resumed",
    SessionAction.COMPLETE: "session_completed",
    SessionAction.CANCEL: "session_cancelled",
    SessionAction.ARCHIVE: "session_archived",
}


@dataclass(frozen=True, slots=True)
class StageAdvanceResult:
    stage: SessionStage
    transition: SessionStageTransition
    event: SessionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class NoteMutationResult:
    note: SessionNote
    event: SessionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class AuditPageResult:
    items: list[AuditLog]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class NotesPageResult:
    items: list[SessionNote]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


class AuditedSessionRepository(ConfiguredSessionRepository):
    """M4 session repository with append-only commands and audit history."""

    def __init__(self, database: Database) -> None:
        super().__init__(database)

    def create(
        self,
        payload: SessionCreate,
        *,
        idempotency_key: str,
    ) -> TransitionResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        fingerprint = _fingerprint(
            {
                "session_number": payload.session_number,
                "node_id": payload.node_id,
                "title": payload.title,
                "test_object": payload.test_object,
                "customer": payload.customer,
                "model": payload.model,
                "serial_number": payload.serial_number,
                "standard": payload.standard,
                "method": payload.method,
                "operator_id": payload.operator_id,
                "responsible_engineer_id": payload.responsible_engineer_id,
                "metadata_payload": payload.metadata_payload,
            }
        )

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    existing = self._create_event_by_key(db_session, normalized_key)
                    if existing is not None:
                        return self._replay_create(
                            db_session,
                            existing,
                            fingerprint=fingerprint,
                        )

                    now = datetime.now(UTC)
                    session_id = str(uuid4())
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
                        created_at=payload.occurred_at,
                        updated_at=payload.occurred_at,
                    )
                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type="session_created",
                        previous_state=None,
                        next_state=SessionState.DRAFT.value,
                        actor_id=payload.actor_id,
                        actor_source=payload.actor_source,
                        reason=payload.reason,
                        payload={
                            "session_number": payload.session_number,
                            "command_sha256": fingerprint,
                        },
                        idempotency_key=normalized_key,
                        occurred_at=payload.occurred_at,
                        inserted_at=now,
                    )
                    audit = self._audit_for_event(
                        event,
                        entity_type="test_session",
                    )
                    db_session.add_all([record, event, audit])
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
                existing = self._create_event_by_key(db_session, normalized_key)
                if existing is not None:
                    return self._replay_create(
                        db_session,
                        existing,
                        fingerprint=fingerprint,
                    )
                existing_session = db_session.scalar(
                    select(TestSession).where(
                        TestSession.session_number == payload.session_number
                    )
                )
                if existing_session is not None:
                    raise SessionConflictError(
                        "session_number_conflict",
                        f"session number {payload.session_number!r} already exists",
                    ) from error
                raise SessionConflictError(
                    "session_create_conflict",
                    "session could not be created because of a persistence conflict",
                ) from error

    def transition(
        self,
        session_id: str,
        action: SessionAction,
        request: SessionTransitionRequest,
        *,
        idempotency_key: str,
    ) -> TransitionResult:
        result = super().transition(
            session_id,
            action,
            request,
            idempotency_key=idempotency_key,
        )
        expected_event_type = _ACTION_EVENT_TYPES[action]
        if result.event.event_type != expected_event_type:
            raise SessionConflictError(
                "idempotency_key_reused",
                "Idempotency-Key was used for another session command",
            )
        return result

    def advance_stage(
        self,
        session_id: str,
        request: StageAdvanceRequest,
        *,
        idempotency_key: str,
    ) -> StageAdvanceResult:
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
                        return self._replay_stage(db_session, record, existing)

                    current_stage = (
                        db_session.get(SessionStage, record.current_stage_id)
                        if record.current_stage_id is not None
                        else None
                    )
                    current_index = (
                        current_stage.sequence_index
                        if current_stage is not None
                        else None
                    )
                    max_index = db_session.scalar(
                        select(func.max(SessionStage.sequence_index)).where(
                            SessionStage.session_id == session_id
                        )
                    )
                    stage_count = max(
                        int(max_index if max_index is not None else -1) + 1,
                        request.sequence_index + 1,
                    )
                    validate_stage_transition(
                        session_state=SessionState(record.state),
                        current_index=current_index,
                        next_index=request.sequence_index,
                        stage_count=stage_count,
                    )

                    target = db_session.scalar(
                        select(SessionStage)
                        .where(
                            SessionStage.session_id == session_id,
                            SessionStage.sequence_index == request.sequence_index,
                        )
                        .with_for_update()
                    )
                    if target is None:
                        target = SessionStage(
                            id=str(uuid4()),
                            session_id=session_id,
                            sequence_index=request.sequence_index,
                            stage_type=request.stage_type.value,
                            name=request.name,
                            description=request.description,
                            planned_duration_seconds=(
                                request.planned_duration_seconds
                            ),
                            entered_at=None,
                            exited_at=None,
                            created_at=request.occurred_at,
                        )
                        db_session.add(target)
                        db_session.flush()
                    elif (
                        target.stage_type != request.stage_type.value
                        or target.name != request.name
                    ):
                        raise SessionConflictError(
                            "stage_definition_conflict",
                            "the stage sequence already has a different definition",
                        )
                    if target.entered_at is not None:
                        raise SessionConflictError(
                            "stage_already_entered",
                            "the target stage has already been entered",
                        )

                    now = datetime.now(UTC)
                    if current_stage is not None:
                        current_stage.exited_at = request.occurred_at
                    target.entered_at = request.occurred_at

                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type="stage_changed",
                        previous_state=record.state,
                        next_state=record.state,
                        actor_id=request.actor_id,
                        actor_source=request.actor_source,
                        reason=request.reason,
                        payload={
                            "from_stage_id": (
                                current_stage.id if current_stage is not None else None
                            ),
                            "to_stage_id": target.id,
                            "from_sequence_index": current_index,
                            "to_sequence_index": request.sequence_index,
                            "stage_type": request.stage_type.value,
                        },
                        idempotency_key=normalized_key,
                        occurred_at=request.occurred_at,
                        inserted_at=now,
                    )
                    transition = SessionStageTransition(
                        id=str(uuid4()),
                        session_id=session_id,
                        session_event_id=event.id,
                        from_stage_id=(
                            current_stage.id if current_stage is not None else None
                        ),
                        to_stage_id=target.id,
                        from_sequence_index=current_index,
                        to_sequence_index=request.sequence_index,
                        actor_id=request.actor_id,
                        reason=request.reason,
                        occurred_at=request.occurred_at,
                        inserted_at=now,
                    )
                    audit = self._audit_for_configuration_event(
                        event,
                        entity_type="session_stage",
                        entity_id=target.id,
                    )
                    record.current_stage_id = target.id
                    record.lock_version += 1
                    record.updated_at = request.occurred_at
                    db_session.add_all([event, transition, audit])
                    db_session.flush()

                for item in (target, transition, event):
                    db_session.expunge(item)
                return StageAdvanceResult(
                    stage=target,
                    transition=transition,
                    event=event,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                record = db_session.get(TestSession, session_id)
                existing = self._event_by_key(
                    db_session,
                    session_id,
                    normalized_key,
                )
                if record is not None and existing is not None:
                    return self._replay_stage(db_session, record, existing)
                raise SessionConflictError(
                    "stage_transition_conflict",
                    "stage transition conflicted with another committed change",
                ) from error

    def add_note(
        self,
        session_id: str,
        request: SessionNoteCreate,
        *,
        idempotency_key: str,
    ) -> NoteMutationResult:
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
                        return self._replay_note(db_session, existing)

                    if request.stage_id is not None:
                        stage = db_session.scalar(
                            select(SessionStage).where(
                                SessionStage.id == request.stage_id,
                                SessionStage.session_id == session_id,
                            )
                        )
                        if stage is None:
                            raise SessionConflictError(
                                "session_stage_not_found",
                                "note stage does not belong to the session",
                            )

                    now = datetime.now(UTC)
                    note = SessionNote(
                        id=str(uuid4()),
                        session_id=session_id,
                        stage_id=request.stage_id,
                        author_id=request.actor_id,
                        body=request.body,
                        created_at=request.occurred_at,
                    )
                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type="note_added",
                        previous_state=record.state,
                        next_state=record.state,
                        actor_id=request.actor_id,
                        actor_source=request.actor_source,
                        reason=request.reason,
                        payload={
                            "note_id": note.id,
                            "stage_id": request.stage_id,
                        },
                        idempotency_key=normalized_key,
                        occurred_at=request.occurred_at,
                        inserted_at=now,
                    )
                    audit = self._audit_for_configuration_event(
                        event,
                        entity_type="session_note",
                        entity_id=note.id,
                    )
                    record.lock_version += 1
                    record.updated_at = request.occurred_at
                    db_session.add_all([note, event, audit])
                    db_session.flush()

                db_session.expunge(note)
                db_session.expunge(event)
                return NoteMutationResult(
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
                if existing is not None:
                    return self._replay_note(db_session, existing)
                raise SessionConflictError(
                    "session_note_conflict",
                    "session note conflicted with another committed change",
                ) from error

    def stages(self, session_id: str) -> list[SessionStage]:
        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)
            items = list(
                db_session.scalars(
                    select(SessionStage)
                    .where(SessionStage.session_id == session_id)
                    .order_by(
                        SessionStage.sequence_index.asc(),
                        SessionStage.id.asc(),
                    )
                )
            )
            for item in items:
                db_session.expunge(item)
            return items

    def notes(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> NotesPageResult:
        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)
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
            return NotesPageResult(
                items=items,
                count=count,
                limit=limit,
                offset=offset,
            )

    def audit(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> AuditPageResult:
        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)
            count = int(
                db_session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.session_id == session_id)
                )
                or 0
            )
            items = list(
                db_session.scalars(
                    select(AuditLog)
                    .where(AuditLog.session_id == session_id)
                    .order_by(
                        AuditLog.occurred_at.asc(),
                        AuditLog.inserted_at.asc(),
                        AuditLog.id.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            for item in items:
                db_session.expunge(item)
            return AuditPageResult(
                items=items,
                count=count,
                limit=limit,
                offset=offset,
            )

    def events(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> SessionEventsResult:
        return super().events(
            session_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def _create_event_by_key(
        db_session: Session,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent).where(
                SessionEvent.event_type == "session_created",
                SessionEvent.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _audit_for_event(
        event: SessionEvent,
        *,
        entity_type: str,
    ) -> AuditLog:
        return AuditedSessionRepository._full_audit(
            event,
            entity_type=entity_type,
            entity_id=event.session_id,
        )

    @staticmethod
    def _audit_for_configuration_event(
        event: SessionEvent,
        *,
        entity_type: str,
        entity_id: str,
    ) -> AuditLog:
        return AuditedSessionRepository._full_audit(
            event,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    @staticmethod
    def _full_audit(
        event: SessionEvent,
        *,
        entity_type: str,
        entity_id: str,
    ) -> AuditLog:
        return AuditLog(
            id=str(uuid4()),
            session_id=event.session_id,
            session_event_id=event.id,
            actor_id=event.actor_id,
            actor_source=event.actor_source,
            action=event.event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload={
                "event_id": event.id,
                "event_type": event.event_type,
                "previous_state": event.previous_state,
                "next_state": event.next_state,
                "reason": event.reason,
                "idempotency_key": event.idempotency_key,
                "event_payload": event.payload,
            },
            occurred_at=event.occurred_at,
            inserted_at=event.inserted_at,
        )

    def _replay_create(
        self,
        db_session: Session,
        event: SessionEvent,
        *,
        fingerprint: str,
    ) -> TransitionResult:
        if event.payload.get("command_sha256") not in {None, fingerprint}:
            raise SessionConflictError(
                "idempotency_key_reused",
                "Idempotency-Key was used with a different create payload",
            )
        record = db_session.get(TestSession, event.session_id)
        if record is None:
            raise SessionConflictError(
                "session_create_replay_conflict",
                "idempotent session result is no longer available",
            )
        db_session.expunge(event)
        db_session.expunge(record)
        return TransitionResult(
            session=record,
            event=event,
            replayed=True,
        )

    def _replay_stage(
        self,
        db_session: Session,
        record: TestSession,
        event: SessionEvent,
    ) -> StageAdvanceResult:
        if event.event_type != "stage_changed":
            raise SessionConflictError(
                "idempotency_key_reused",
                "Idempotency-Key was used for another session command",
            )
        target_id = str(event.payload["to_stage_id"])
        stage = db_session.get(SessionStage, target_id)
        transition = db_session.scalar(
            select(SessionStageTransition).where(
                SessionStageTransition.session_event_id == event.id
            )
        )
        if stage is None or transition is None:
            raise SessionConflictError(
                "stage_replay_conflict",
                "idempotent stage result is no longer available",
            )
        for item in (stage, transition, event, record):
            db_session.expunge(item)
        return StageAdvanceResult(
            stage=stage,
            transition=transition,
            event=event,
            replayed=True,
        )

    def _replay_note(
        self,
        db_session: Session,
        event: SessionEvent,
    ) -> NoteMutationResult:
        if event.event_type != "note_added":
            raise SessionConflictError(
                "idempotency_key_reused",
                "Idempotency-Key was used for another session command",
            )
        note_id = str(event.payload["note_id"])
        note = db_session.get(SessionNote, note_id)
        if note is None:
            raise SessionConflictError(
                "note_replay_conflict",
                "idempotent note result is no longer available",
            )
        db_session.expunge(note)
        db_session.expunge(event)
        return NoteMutationResult(
            note=note,
            event=event,
            replayed=True,
        )


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
