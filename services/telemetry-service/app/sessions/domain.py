from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final


class SessionState(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class SessionAction(StrEnum):
    PREPARE = "prepare"
    START = "start"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    CANCEL = "cancel"
    ARCHIVE = "archive"


class SessionStage(StrEnum):
    PREPARATION = "preparation"
    PRECONDITIONING = "preconditioning"
    STABILIZATION = "stabilization"
    MAIN_TEST = "main_test"
    DEFROST = "defrost"
    RECOVERY = "recovery"
    COMPLETION = "completion"
    REPORT = "report"


class SessionDomainError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        current_state: SessionState | None = None,
        action: SessionAction | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.current_state = current_state
        self.action = action


@dataclass(frozen=True, slots=True)
class TransitionCommand:
    idempotency_key: str
    actor_id: str
    occurred_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        idempotency_key = self.idempotency_key.strip()
        actor_id = self.actor_id.strip()
        reason = self.reason.strip() if self.reason is not None else None

        if not idempotency_key:
            raise SessionDomainError(
                "invalid_transition_command",
                "idempotency_key must not be empty",
            )
        if len(idempotency_key) > 128:
            raise SessionDomainError(
                "invalid_transition_command",
                "idempotency_key must not exceed 128 characters",
            )
        if not actor_id:
            raise SessionDomainError(
                "invalid_transition_command",
                "actor_id must not be empty",
            )
        if len(actor_id) > 128:
            raise SessionDomainError(
                "invalid_transition_command",
                "actor_id must not exceed 128 characters",
            )
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise SessionDomainError(
                "invalid_transition_command",
                "occurred_at must be timezone-aware",
            )
        if reason is not None and len(reason) > 2000:
            raise SessionDomainError(
                "invalid_transition_command",
                "reason must not exceed 2000 characters",
            )

        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "reason", reason or None)


@dataclass(frozen=True, slots=True)
class SessionTransition:
    previous_state: SessionState
    next_state: SessionState
    action: SessionAction
    event_type: str
    command: TransitionCommand


@dataclass(frozen=True, slots=True)
class StageTransition:
    previous_index: int | None
    next_index: int


_ALLOWED_TRANSITIONS: Final[dict[tuple[SessionState, SessionAction], SessionState]] = {
    (SessionState.DRAFT, SessionAction.PREPARE): SessionState.READY,
    (SessionState.DRAFT, SessionAction.CANCEL): SessionState.CANCELLED,
    (SessionState.READY, SessionAction.START): SessionState.RUNNING,
    (SessionState.READY, SessionAction.CANCEL): SessionState.CANCELLED,
    (SessionState.RUNNING, SessionAction.PAUSE): SessionState.PAUSED,
    (SessionState.RUNNING, SessionAction.COMPLETE): SessionState.COMPLETED,
    (SessionState.PAUSED, SessionAction.RESUME): SessionState.RUNNING,
    (SessionState.PAUSED, SessionAction.CANCEL): SessionState.CANCELLED,
    (SessionState.COMPLETED, SessionAction.ARCHIVE): SessionState.ARCHIVED,
    (SessionState.CANCELLED, SessionAction.ARCHIVE): SessionState.ARCHIVED,
}

_EVENT_TYPES: Final[dict[SessionAction, str]] = {
    SessionAction.PREPARE: "session_prepared",
    SessionAction.START: "session_started",
    SessionAction.PAUSE: "session_paused",
    SessionAction.RESUME: "session_resumed",
    SessionAction.COMPLETE: "session_completed",
    SessionAction.CANCEL: "session_cancelled",
    SessionAction.ARCHIVE: "session_archived",
}

_IMMUTABLE_STATES: Final[frozenset[SessionState]] = frozenset(
    {
        SessionState.COMPLETED,
        SessionState.CANCELLED,
        SessionState.ARCHIVED,
    }
)

_TELEMETRY_ATTRIBUTION_STATES: Final[frozenset[SessionState]] = frozenset(
    {
        SessionState.RUNNING,
        SessionState.PAUSED,
    }
)

_CONFIGURATION_MUTABLE_STATES: Final[frozenset[SessionState]] = frozenset(
    {
        SessionState.DRAFT,
        SessionState.READY,
    }
)


def transition_session(
    current_state: SessionState,
    action: SessionAction,
    command: TransitionCommand,
) -> SessionTransition:
    if action is SessionAction.CANCEL and command.reason is None:
        raise SessionDomainError(
            "transition_reason_required",
            "cancel requires a reason",
            current_state=current_state,
            action=action,
        )

    next_state = _ALLOWED_TRANSITIONS.get((current_state, action))
    if next_state is None:
        code = (
            "session_immutable"
            if current_state in _IMMUTABLE_STATES
            else "invalid_session_transition"
        )
        raise SessionDomainError(
            code,
            f"cannot {action.value} a session in {current_state.value} state",
            current_state=current_state,
            action=action,
        )

    return SessionTransition(
        previous_state=current_state,
        next_state=next_state,
        action=action,
        event_type=_EVENT_TYPES[action],
        command=command,
    )


def validate_stage_transition(
    *,
    session_state: SessionState,
    current_index: int | None,
    next_index: int,
    stage_count: int,
) -> StageTransition:
    if session_state is not SessionState.RUNNING:
        raise SessionDomainError(
            "invalid_stage_transition",
            "stages can advance only while the session is running",
            current_state=session_state,
        )
    if stage_count < 1:
        raise SessionDomainError(
            "invalid_stage_plan",
            "stage_count must be positive",
            current_state=session_state,
        )
    if current_index is not None and not 0 <= current_index < stage_count:
        raise SessionDomainError(
            "invalid_stage_transition",
            "current stage index is outside the configured stage plan",
            current_state=session_state,
        )
    if not 0 <= next_index < stage_count:
        raise SessionDomainError(
            "invalid_stage_transition",
            "next stage index is outside the configured stage plan",
            current_state=session_state,
        )

    expected_next = 0 if current_index is None else current_index + 1
    if next_index != expected_next:
        raise SessionDomainError(
            "invalid_stage_transition",
            f"next stage index must be {expected_next}",
            current_state=session_state,
        )

    return StageTransition(previous_index=current_index, next_index=next_index)


def session_accepts_telemetry(state: SessionState) -> bool:
    return state in _TELEMETRY_ATTRIBUTION_STATES


def session_configuration_is_mutable(state: SessionState) -> bool:
    return state in _CONFIGURATION_MUTABLE_STATES


def session_is_immutable(state: SessionState) -> bool:
    return state in _IMMUTABLE_STATES
