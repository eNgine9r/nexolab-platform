from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.alerts.domain import (
    AlertCondition,
    AlertEvaluationDecision,
    AlertEvaluationSnapshot,
    AlertRuleConfiguration,
    TelemetryObservation,
)
from app.alerts.evaluator import evaluate_threshold


def observed(seconds: int, value: float | None, event_id: str) -> TelemetryObservation:
    return TelemetryObservation(
        event_id=event_id,
        captured_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
        + timedelta(seconds=seconds),
        value=value,
    )


def high_rule(**overrides: int | float) -> AlertRuleConfiguration:
    values: dict[str, object] = {
        "condition": AlertCondition.THRESHOLD_HIGH,
        "trigger_threshold": 8.0,
        "clear_threshold": 7.0,
        "minimum_duration_seconds": 60,
        "clear_duration_seconds": 30,
        "debounce_seconds": 0,
        "cooldown_seconds": 120,
    }
    values.update(overrides)
    return AlertRuleConfiguration(**values)  # type: ignore[arg-type]


def test_short_spike_does_not_trigger() -> None:
    snapshot = AlertEvaluationSnapshot()

    pending = evaluate_threshold(high_rule(), snapshot, observed(0, 8.5, "event-1"))
    assert pending.decision is AlertEvaluationDecision.START_TRIGGER_PENDING

    reset = evaluate_threshold(
        high_rule(), pending.snapshot, observed(30, 7.5, "event-2")
    )
    assert reset.decision is AlertEvaluationDecision.RESET_TRIGGER_PENDING
    assert reset.snapshot.active_alert_id is None
    assert reset.snapshot.trigger_pending_since is None


def test_sustained_excursion_triggers_exactly_once() -> None:
    configuration = high_rule()
    pending = evaluate_threshold(
        configuration,
        AlertEvaluationSnapshot(),
        observed(0, 8.5, "event-1"),
    )
    triggered = evaluate_threshold(
        configuration,
        pending.snapshot,
        observed(60, 9.0, "event-2"),
    )
    assert triggered.decision is AlertEvaluationDecision.TRIGGER
    assert triggered.snapshot.maximum_deviation == pytest.approx(1.0)

    active_snapshot = replace(triggered.snapshot, active_alert_id="alert-1")
    still_active = evaluate_threshold(
        configuration,
        active_snapshot,
        observed(61, 9.2, "event-3"),
    )
    assert still_active.decision is AlertEvaluationDecision.NONE
    assert still_active.snapshot.maximum_deviation == pytest.approx(1.2)


def test_hysteresis_prevents_flapping_and_clear_duration_resolves() -> None:
    configuration = high_rule()
    active = AlertEvaluationSnapshot(active_alert_id="alert-1")

    inside_hysteresis = evaluate_threshold(
        configuration,
        active,
        observed(0, 7.5, "event-1"),
    )
    assert inside_hysteresis.decision is AlertEvaluationDecision.NONE

    clearing = evaluate_threshold(
        configuration,
        inside_hysteresis.snapshot,
        observed(10, 6.9, "event-2"),
    )
    assert clearing.decision is AlertEvaluationDecision.START_CLEAR_PENDING

    resolved = evaluate_threshold(
        configuration,
        clearing.snapshot,
        observed(40, 6.8, "event-3"),
    )
    assert resolved.decision is AlertEvaluationDecision.RESOLVE
    assert resolved.snapshot.active_alert_id is None
    assert resolved.snapshot.cooldown_until == observed(160, 0, "unused").captured_at


def test_duplicate_and_out_of_order_observations_are_ignored() -> None:
    snapshot = AlertEvaluationSnapshot(
        last_event_id="event-2",
        last_captured_at=observed(20, 7.0, "event-2").captured_at,
    )

    duplicate = evaluate_threshold(
        high_rule(), snapshot, observed(20, 9.0, "event-2")
    )
    assert duplicate.decision is AlertEvaluationDecision.IGNORE_DUPLICATE
    assert duplicate.snapshot is snapshot

    old = evaluate_threshold(high_rule(), snapshot, observed(19, 9.0, "event-1"))
    assert old.decision is AlertEvaluationDecision.IGNORE_OUT_OF_ORDER
    assert old.snapshot is snapshot


def test_cooldown_suppresses_immediate_retrigger() -> None:
    snapshot = AlertEvaluationSnapshot(
        cooldown_until=observed(120, 0, "unused").captured_at
    )
    result = evaluate_threshold(high_rule(), snapshot, observed(30, 10.0, "event-1"))
    assert result.decision is AlertEvaluationDecision.IGNORE_COOLDOWN
    assert result.snapshot.trigger_pending_since is None


def test_low_threshold_validation_and_evaluation() -> None:
    configuration = AlertRuleConfiguration(
        condition=AlertCondition.THRESHOLD_LOW,
        trigger_threshold=-5.0,
        clear_threshold=-4.0,
    )
    triggered = evaluate_threshold(
        configuration,
        AlertEvaluationSnapshot(),
        observed(0, -5.5, "event-1"),
    )
    assert triggered.decision is AlertEvaluationDecision.TRIGGER


def test_invalid_hysteresis_is_rejected() -> None:
    with pytest.raises(ValueError, match="clear value"):
        AlertRuleConfiguration(
            condition=AlertCondition.THRESHOLD_HIGH,
            trigger_threshold=8.0,
            clear_threshold=9.0,
        )
