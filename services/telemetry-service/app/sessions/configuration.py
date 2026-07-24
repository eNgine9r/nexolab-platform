from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.db import Database
from app.sessions.configuration_bindings import BindingRepositoryMixin
from app.sessions.configuration_limits import LimitRepositoryMixin
from app.sessions.configuration_schemas import ConfigurationCommand
from app.sessions.configuration_support import ConfigurationSupportMixin
from app.sessions.domain import (
    SessionAction,
    SessionState,
    TransitionCommand,
    transition_session,
)
from app.sessions.models import (
    AuditLog,
    SessionChannelBinding,
    SessionEvent,
    SessionStage as SessionStageRecord,
    SessionStageTransition,
    TestSession,
)
from app.sessions.repository import (
    SessionConflictError,
    SessionRepository,
    TransitionResult,
)
from app.sessions.schemas import SessionCreate, SessionTransitionRequest
from app.sessions.stage_repository import StageRepositoryMixin
from app.sessions.time_utils import as_utc


class ConfiguredSessionRepository(
    BindingRepositoryMixin,
    LimitRepositoryMixin,
    StageRepositoryMixin,
    ConfigurationSupportMixin,
    SessionRepository,
):
    def __init__(self, database: Database) -> None:
        SessionRepository.__init__(self, database)

    def _configuration_event(
        self,
        record: TestSession,
        *,
        event_type: str,
        command: ConfigurationCommand,
        idempotency_key: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> SessionEvent:
        event = ConfigurationSupportMixin._configuration_event(
            record,
            event_type=event_type,
            command=command,
            idempotency_key=idempotency_key,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        db_session = object_session(record)
        if db_session is None:
            raise RuntimeError("session record is not attached to a transaction")
        db_session.add(event)
        db_session.flush([event])
        return event

    def _audit_for_event(
        self,
        event: SessionEvent,
        *,
        entity_type: str,
    ) -> AuditLog:
        db_session = object_session(event)
        if db_session is not None and event in db_session.new:
            db_session.flush([event])
        return SessionRepository._audit_for_event(
            event,
            entity_type=entity_type,
        )

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
        audit = SessionRepository._audit_for_event(
            event,
            entity_type="test_session",
        )

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    db_session.add(record)
                    db_session.flush([record])
                    db_session.add(event)
                    db_session.flush([event])
                    db_session.add(audit)
                    db_session.flush([audit])
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
                    record = self._locked_session(db_session, session_id)
                    existing = self._event_by_key(
                        db_session,
                        session_id,
                        normalized_key,
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
                    event_payload: dict[str, Any] = {"action": action.value}
                    start_stage: SessionStageRecord | None = None

                    if action is SessionAction.START:
                        bindings = self._bindings_for_session(
                            db_session,
                            session_id,
                            include_released=False,
                        )
                        for binding in bindings:
                            if binding.activated_at is None:
                                binding.activated_at = request.occurred_at

                        stages = self._stages_for_session(db_session, session_id)
                        if stages:
                            start_stage = stages[0]
                            start_stage.entered_at = request.occurred_at
                            record.current_stage_id = start_stage.id
                            event_payload.update(
                                {
                                    "stage_id": start_stage.id,
                                    "stage_sequence_index": (
                                        start_stage.sequence_index
                                    ),
                                }
                            )

                        db_session.flush()
                        snapshot = self._freeze_configuration(
                            db_session,
                            record,
                            actor_id=request.actor_id,
                            captured_at=request.occurred_at,
                            source="session_start",
                        )
                        event_payload.update(
                            {
                                "config_snapshot_id": snapshot.id,
                                "config_snapshot_version": snapshot.version,
                                "production_complete": snapshot.payload[
                                    "production_contract"
                                ]["complete"],
                            }
                        )
                    elif action in {SessionAction.COMPLETE, SessionAction.CANCEL}:
                        active_bindings = list(
                            db_session.scalars(
                                select(SessionChannelBinding).where(
                                    SessionChannelBinding.session_id == session_id,
                                    SessionChannelBinding.activated_at.is_not(None),
                                    SessionChannelBinding.released_at.is_(None),
                                )
                            )
                        )
                        for binding in active_bindings:
                            if (
                                binding.activated_at is not None
                                and as_utc(request.occurred_at)
                                < as_utc(binding.activated_at)
                            ):
                                raise SessionConflictError(
                                    "binding_release_time_invalid",
                                    "session completion cannot precede "
                                    "binding activation",
                                )
                            binding.released_at = request.occurred_at

                        if record.current_stage_id is not None:
                            current_stage = db_session.get(
                                SessionStageRecord,
                                record.current_stage_id,
                            )
                            if (
                                current_stage is not None
                                and current_stage.exited_at is None
                            ):
                                current_stage.exited_at = request.occurred_at

                    event = SessionEvent(
                        id=str(uuid4()),
                        session_id=session_id,
                        event_type=transition.event_type,
                        previous_state=transition.previous_state.value,
                        next_state=transition.next_state.value,
                        actor_id=request.actor_id,
                        actor_source=request.actor_source,
                        reason=request.reason,
                        payload=event_payload,
                        idempotency_key=normalized_key,
                        occurred_at=request.occurred_at,
                        inserted_at=request.occurred_at,
                    )
                    record.state = transition.next_state.value
                    record.lock_version += 1
                    record.updated_at = request.occurred_at
                    self._apply_transition_timestamp(
                        record,
                        action=action,
                        occurred_at=request.occurred_at,
                    )

                    db_session.add(event)
                    db_session.flush([event])
                    if start_stage is not None:
                        stage_transition = SessionStageTransition(
                            id=str(uuid4()),
                            session_id=session_id,
                            session_event_id=event.id,
                            from_stage_id=None,
                            to_stage_id=start_stage.id,
                            from_sequence_index=None,
                            to_sequence_index=start_stage.sequence_index,
                            actor_id=request.actor_id,
                            reason=request.reason,
                            occurred_at=request.occurred_at,
                            inserted_at=request.occurred_at,
                        )
                        db_session.add(stage_transition)
                        db_session.flush([stage_transition])
                    audit = self._audit_for_event(
                        event,
                        entity_type="test_session",
                    )
                    db_session.add(audit)
                    db_session.flush([audit])

                db_session.expunge(event)
                db_session.expunge(record)
                return TransitionResult(
                    session=record,
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
                record = db_session.get(TestSession, session_id)
                if existing is not None and record is not None:
                    db_session.expunge(existing)
                    db_session.expunge(record)
                    return TransitionResult(
                        session=record,
                        event=existing,
                        replayed=True,
                    )
                code = (
                    "active_channel_lease_conflict"
                    if action is SessionAction.START
                    else "session_transition_conflict"
                )
                raise SessionConflictError(
                    code,
                    "session transition conflicted with another committed change",
                ) from error
