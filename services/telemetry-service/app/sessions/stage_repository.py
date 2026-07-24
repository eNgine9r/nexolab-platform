from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.sessions.domain import (
    SessionDomainError,
    SessionState,
    validate_stage_transition,
)
from app.sessions.models import (
    SessionEvent,
    SessionStage as SessionStageRecord,
    SessionStageTransition,
    TestSession,
)
from app.sessions.repository import SessionConflictError
from app.sessions.stage_schemas import StageAdvanceRequest, StagePlanCreate


@dataclass(frozen=True, slots=True)
class StagePlanResult:
    stages: list[SessionStageRecord]
    event: SessionEvent
    replayed: bool


@dataclass(frozen=True, slots=True)
class StageAdvanceResult:
    session: TestSession
    current_stage: SessionStageRecord
    transition: SessionStageTransition
    event: SessionEvent
    replayed: bool


class StageRepositoryMixin:
    def configure_stage_plan(
        self,
        session_id: str,
        payload: StagePlanCreate,
        *,
        idempotency_key: str,
    ) -> StagePlanResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                record = self._locked_session(db_session, session_id)
                existing_event = self._event_by_key(
                    db_session,
                    session_id,
                    normalized_key,
                )
                if existing_event is not None:
                    if existing_event.event_type != "session_stage_plan_configured":
                        raise SessionConflictError(
                            "idempotency_key_reused",
                            "Idempotency-Key was used for another session command",
                        )
                    stages = self._stages_for_session(db_session, session_id)
                    return self._detach_stage_plan_result(
                        db_session,
                        stages,
                        existing_event,
                        replayed=True,
                    )

                state = SessionState(record.state)
                if state not in {SessionState.DRAFT, SessionState.READY}:
                    raise SessionDomainError(
                        "stage_plan_immutable",
                        f"stage plan cannot be configured in {state.value} state",
                        current_state=state,
                    )
                if self._stages_for_session(db_session, session_id):
                    raise SessionConflictError(
                        "stage_plan_already_configured",
                        "the session already has a stage plan",
                    )

                stages = [
                    SessionStageRecord(
                        id=str(uuid4()),
                        session_id=session_id,
                        sequence_index=index,
                        stage_type=definition.stage_type.value,
                        name=definition.name,
                        description=definition.description,
                        planned_duration_seconds=(
                            definition.planned_duration_seconds
                        ),
                        entered_at=None,
                        exited_at=None,
                        created_at=payload.occurred_at,
                    )
                    for index, definition in enumerate(payload.stages)
                ]
                event = SessionEvent(
                    id=str(uuid4()),
                    session_id=session_id,
                    event_type="session_stage_plan_configured",
                    previous_state=record.state,
                    next_state=record.state,
                    actor_id=payload.actor_id,
                    actor_source=payload.actor_source,
                    reason=None,
                    payload={
                        "stage_ids": [stage.id for stage in stages],
                        "stage_count": len(stages),
                    },
                    idempotency_key=normalized_key,
                    occurred_at=payload.occurred_at,
                    inserted_at=payload.occurred_at,
                )
                db_session.add_all(stages)
                db_session.add(event)
                db_session.add(
                    self._audit_for_event(
                        event,
                        entity_type="session_stage_plan",
                    )
                )
                record.lock_version += 1
                record.updated_at = payload.occurred_at
                db_session.flush()

            return self._detach_stage_plan_result(
                db_session,
                stages,
                event,
                replayed=False,
            )

    def advance_stage(
        self,
        session_id: str,
        payload: StageAdvanceRequest,
        *,
        idempotency_key: str,
    ) -> StageAdvanceResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                record = self._locked_session(db_session, session_id)
                existing_event = self._event_by_key(
                    db_session,
                    session_id,
                    normalized_key,
                )
                if existing_event is not None:
                    if existing_event.event_type != "session_stage_advanced":
                        raise SessionConflictError(
                            "idempotency_key_reused",
                            "Idempotency-Key was used for another session command",
                        )
                    transition_id = str(existing_event.payload["transition_id"])
                    stage_id = str(existing_event.payload["to_stage_id"])
                    transition = db_session.get(
                        SessionStageTransition,
                        transition_id,
                    )
                    stage = db_session.get(SessionStageRecord, stage_id)
                    if transition is None or stage is None:
                        raise SessionConflictError(
                            "stage_transition_replay_conflict",
                            "idempotent stage transition is no longer available",
                        )
                    return self._detach_stage_advance_result(
                        db_session,
                        record,
                        stage,
                        transition,
                        existing_event,
                        replayed=True,
                    )

                stages = self._stages_for_session(db_session, session_id)
                current_index = next(
                    (
                        stage.sequence_index
                        for stage in stages
                        if stage.id == record.current_stage_id
                    ),
                    None,
                )
                next_index = 0 if current_index is None else current_index + 1
                transition_domain = validate_stage_transition(
                    session_state=SessionState(record.state),
                    current_index=current_index,
                    next_index=next_index,
                    stage_count=len(stages),
                )
                next_stage = stages[transition_domain.next_index]
                previous_stage = (
                    stages[transition_domain.previous_index]
                    if transition_domain.previous_index is not None
                    else None
                )
                if previous_stage is not None:
                    previous_stage.exited_at = payload.occurred_at
                next_stage.entered_at = payload.occurred_at
                record.current_stage_id = next_stage.id
                record.lock_version += 1
                record.updated_at = payload.occurred_at

                event = SessionEvent(
                    id=str(uuid4()),
                    session_id=session_id,
                    event_type="session_stage_advanced",
                    previous_state=record.state,
                    next_state=record.state,
                    actor_id=payload.actor_id,
                    actor_source=payload.actor_source,
                    reason=payload.reason,
                    payload={},
                    idempotency_key=normalized_key,
                    occurred_at=payload.occurred_at,
                    inserted_at=payload.occurred_at,
                )
                transition = SessionStageTransition(
                    id=str(uuid4()),
                    session_id=session_id,
                    session_event_id=event.id,
                    from_stage_id=(
                        previous_stage.id if previous_stage is not None else None
                    ),
                    to_stage_id=next_stage.id,
                    from_sequence_index=transition_domain.previous_index,
                    to_sequence_index=transition_domain.next_index,
                    actor_id=payload.actor_id,
                    reason=payload.reason,
                    occurred_at=payload.occurred_at,
                    inserted_at=payload.occurred_at,
                )
                event.payload = {
                    "transition_id": transition.id,
                    "from_stage_id": transition.from_stage_id,
                    "to_stage_id": transition.to_stage_id,
                    "from_sequence_index": transition.from_sequence_index,
                    "to_sequence_index": transition.to_sequence_index,
                }
                db_session.add_all([event, transition])
                db_session.add(
                    self._audit_for_event(
                        event,
                        entity_type="session_stage",
                    )
                )
                db_session.flush()

            return self._detach_stage_advance_result(
                db_session,
                record,
                next_stage,
                transition,
                event,
                replayed=False,
            )

    def stages(self, session_id: str) -> list[SessionStageRecord]:
        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)
            stages = self._stages_for_session(db_session, session_id)
            for stage in stages:
                db_session.expunge(stage)
            return stages

    @staticmethod
    def _stages_for_session(
        db_session: Session,
        session_id: str,
    ) -> list[SessionStageRecord]:
        return list(
            db_session.scalars(
                select(SessionStageRecord)
                .where(SessionStageRecord.session_id == session_id)
                .order_by(SessionStageRecord.sequence_index.asc())
            )
        )

    @staticmethod
    def _detach_stage_plan_result(
        db_session: Session,
        stages: list[SessionStageRecord],
        event: SessionEvent,
        *,
        replayed: bool,
    ) -> StagePlanResult:
        for stage in stages:
            db_session.expunge(stage)
        db_session.expunge(event)
        return StagePlanResult(stages=stages, event=event, replayed=replayed)

    @staticmethod
    def _detach_stage_advance_result(
        db_session: Session,
        record: TestSession,
        stage: SessionStageRecord,
        transition: SessionStageTransition,
        event: SessionEvent,
        *,
        replayed: bool,
    ) -> StageAdvanceResult:
        for item in (record, stage, transition, event):
            db_session.expunge(item)
        return StageAdvanceResult(
            session=record,
            current_stage=stage,
            transition=transition,
            event=event,
            replayed=replayed,
        )
