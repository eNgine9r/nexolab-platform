from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.sessions import (
    SessionAction,
    SessionDomainError,
    SessionState,
    TransitionCommand,
    session_accepts_telemetry,
    session_configuration_is_mutable,
    session_is_immutable,
    transition_session,
    validate_stage_transition,
)


VALID_TRANSITIONS = {
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


def command(action: SessionAction = SessionAction.START) -> TransitionCommand:
    return TransitionCommand(
        idempotency_key=f"test-{action.value}",
        actor_id="operator-1",
        occurred_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        reason="operator cancelled the test" if action is SessionAction.CANCEL else None,
    )


@pytest.mark.parametrize(
    ("current_state", "action", "expected_state"),
    [
        (*transition, next_state)
        for transition, next_state in VALID_TRANSITIONS.items()
    ],
)
def test_all_valid_session_transitions(
    current_state: SessionState,
    action: SessionAction,
    expected_state: SessionState,
) -> None:
    result = transition_session(current_state, action, command(action))

    assert result.previous_state is current_state
    assert result.next_state is expected_state
    assert result.action is action
    assert result.event_type == f"session_{action.value}d" or result.event_type in {
        "session_prepared",
        "session_cancelled",
        "session_completed",
        "session_archived",
    }
    assert result.command.idempotency_key == f"test-{action.value}"


INVALID_TRANSITIONS = [
    (state, action)
    for state in SessionState
    for action in SessionAction
    if (state, action) not in VALID_TRANSITIONS
]


@pytest.mark.parametrize(("current_state", "action"), INVALID_TRANSITIONS)
def test_all_invalid_session_transitions_are_rejected(
    current_state: SessionState,
    action: SessionAction,
) -> None:
    with pytest.raises(SessionDomainError) as error:
        transition_session(current_state, action, command(action))

    assert error.value.current_state is current_state
    assert error.value.action is action
    assert error.value.code in {
        "invalid_session_transition",
        "session_immutable",
    }


def test_cancel_requires_a_reason() -> None:
    without_reason = TransitionCommand(
        idempotency_key="cancel-without-reason",
        actor_id="operator-1",
        occurred_at=datetime.now(UTC),
    )

    with pytest.raises(SessionDomainError) as error:
        transition_session(
            SessionState.DRAFT,
            SessionAction.CANCEL,
            without_reason,
        )

    assert error.value.code == "transition_reason_required"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (SessionState.DRAFT, False),
        (SessionState.READY, False),
        (SessionState.RUNNING, True),
        (SessionState.PAUSED, True),
        (SessionState.COMPLETED, False),
        (SessionState.CANCELLED, False),
        (SessionState.ARCHIVED, False),
    ],
)
def test_telemetry_attribution_remains_active_while_paused(
    state: SessionState,
    expected: bool,
) -> None:
    assert session_accepts_telemetry(state) is expected


@pytest.mark.parametrize(
    ("state", "configuration_mutable", "immutable"),
    [
        (SessionState.DRAFT, True, False),
        (SessionState.READY, True, False),
        (SessionState.RUNNING, False, False),
        (SessionState.PAUSED, False, False),
        (SessionState.COMPLETED, False, True),
        (SessionState.CANCELLED, False, True),
        (SessionState.ARCHIVED, False, True),
    ],
)
def test_mutability_contract(
    state: SessionState,
    configuration_mutable: bool,
    immutable: bool,
) -> None:
    assert session_configuration_is_mutable(state) is configuration_mutable
    assert session_is_immutable(state) is immutable


def test_running_session_enters_stages_in_configured_order() -> None:
    first = validate_stage_transition(
        session_state=SessionState.RUNNING,
        current_index=None,
        next_index=0,
        stage_count=4,
    )
    second = validate_stage_transition(
        session_state=SessionState.RUNNING,
        current_index=first.next_index,
        next_index=1,
        stage_count=4,
    )

    assert first.previous_index is None
    assert first.next_index == 0
    assert second.previous_index == 0
    assert second.next_index == 1


@pytest.mark.parametrize(
    "state",
    [
        SessionState.DRAFT,
        SessionState.READY,
        SessionState.PAUSED,
        SessionState.COMPLETED,
        SessionState.CANCELLED,
        SessionState.ARCHIVED,
    ],
)
def test_stage_progression_is_rejected_when_workflow_is_not_running(
    state: SessionState,
) -> None:
    with pytest.raises(SessionDomainError) as error:
        validate_stage_transition(
            session_state=state,
            current_index=None,
            next_index=0,
            stage_count=2,
        )

    assert error.value.code == "invalid_stage_transition"


@pytest.mark.parametrize(
    ("current_index", "next_index", "stage_count"),
    [
        (None, 1, 3),
        (0, 0, 3),
        (0, 2, 3),
        (2, 3, 3),
        (-1, 0, 3),
        (3, 0, 3),
    ],
)
def test_invalid_stage_indices_are_rejected(
    current_index: int | None,
    next_index: int,
    stage_count: int,
) -> None:
    with pytest.raises(SessionDomainError) as error:
        validate_stage_transition(
            session_state=SessionState.RUNNING,
            current_index=current_index,
            next_index=next_index,
            stage_count=stage_count,
        )

    assert error.value.code == "invalid_stage_transition"


def test_empty_stage_plan_is_rejected() -> None:
    with pytest.raises(SessionDomainError) as error:
        validate_stage_transition(
            session_state=SessionState.RUNNING,
            current_index=None,
            next_index=0,
            stage_count=0,
        )

    assert error.value.code == "invalid_stage_plan"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"idempotency_key": ""},
        {"idempotency_key": "x" * 129},
        {"actor_id": ""},
        {"actor_id": "x" * 129},
        {"occurred_at": datetime(2026, 7, 24, 8, 0)},
        {"reason": "x" * 2001},
    ],
)
def test_invalid_transition_commands_are_rejected(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "idempotency_key": "command-1",
        "actor_id": "operator-1",
        "occurred_at": datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        "reason": None,
    }
    values.update(kwargs)

    with pytest.raises(SessionDomainError) as error:
        TransitionCommand(**values)  # type: ignore[arg-type]

    assert error.value.code == "invalid_transition_command"


def test_transition_command_normalizes_text_fields() -> None:
    normalized = TransitionCommand(
        idempotency_key="  command-1  ",
        actor_id="  operator-1  ",
        occurred_at=datetime(2026, 7, 24, 8, 0, tzinfo=UTC),
        reason="  controlled cancellation  ",
    )

    assert normalized.idempotency_key == "command-1"
    assert normalized.actor_id == "operator-1"
    assert normalized.reason == "controlled cancellation"
