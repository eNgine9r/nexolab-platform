from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from app.alerts.domain import (
    AlertEvaluationDecision,
    AlertEvaluationResult,
    AlertEvaluationSnapshot,
    AlertRuleConfiguration,
    TelemetryObservation,
    accepted_snapshot,
)


def evaluate_threshold(
    configuration: AlertRuleConfiguration,
    snapshot: AlertEvaluationSnapshot,
    observation: TelemetryObservation,
) -> AlertEvaluationResult:
    """Evaluate one observation without performing persistence side effects.

    Duplicate event IDs and observations older than the accepted watermark are
    ignored. Trigger and clear durations require a continuous condition, while
    hysteresis is represented by separate trigger and clear thresholds.
    """

    if snapshot.last_event_id == observation.event_id:
        return AlertEvaluationResult(
            AlertEvaluationDecision.IGNORE_DUPLICATE,
            snapshot,
        )
    if (
        snapshot.last_captured_at is not None
        and observation.captured_at < snapshot.last_captured_at
    ):
        return AlertEvaluationResult(
            AlertEvaluationDecision.IGNORE_OUT_OF_ORDER,
            snapshot,
        )
    if observation.value is None:
        next_snapshot = accepted_snapshot(
            snapshot,
            observation,
            trigger_pending_since=None,
            clear_pending_since=None,
            maximum_deviation=snapshot.maximum_deviation,
        )
        return AlertEvaluationResult(
            AlertEvaluationDecision.IGNORE_INVALID_VALUE,
            next_snapshot,
        )

    value = observation.value
    deviation = configuration.deviation(value)

    if snapshot.active_alert_id is None:
        if (
            snapshot.cooldown_until is not None
            and observation.captured_at < snapshot.cooldown_until
        ):
            next_snapshot = accepted_snapshot(
                snapshot,
                observation,
                trigger_pending_since=None,
                clear_pending_since=None,
                maximum_deviation=0.0,
            )
            return AlertEvaluationResult(
                AlertEvaluationDecision.IGNORE_COOLDOWN,
                next_snapshot,
                deviation,
            )

        if not configuration.is_triggered(value):
            decision = (
                AlertEvaluationDecision.RESET_TRIGGER_PENDING
                if snapshot.trigger_pending_since is not None
                else AlertEvaluationDecision.NONE
            )
            next_snapshot = accepted_snapshot(
                snapshot,
                observation,
                trigger_pending_since=None,
                clear_pending_since=None,
                maximum_deviation=0.0,
            )
            return AlertEvaluationResult(decision, next_snapshot, deviation)

        pending_since = snapshot.trigger_pending_since or observation.captured_at
        due_at = pending_since + timedelta(
            seconds=configuration.trigger_duration_seconds
        )
        decision = (
            AlertEvaluationDecision.TRIGGER
            if observation.captured_at >= due_at
            else AlertEvaluationDecision.START_TRIGGER_PENDING
        )
        next_snapshot = accepted_snapshot(
            snapshot,
            observation,
            trigger_pending_since=(
                None if decision is AlertEvaluationDecision.TRIGGER else pending_since
            ),
            clear_pending_since=None,
            maximum_deviation=max(snapshot.maximum_deviation, deviation),
        )
        return AlertEvaluationResult(decision, next_snapshot, deviation)

    maximum_deviation = max(snapshot.maximum_deviation, deviation)
    if not configuration.is_clear(value):
        decision = (
            AlertEvaluationDecision.RESET_CLEAR_PENDING
            if snapshot.clear_pending_since is not None
            else AlertEvaluationDecision.NONE
        )
        next_snapshot = accepted_snapshot(
            snapshot,
            observation,
            trigger_pending_since=None,
            clear_pending_since=None,
            maximum_deviation=maximum_deviation,
        )
        return AlertEvaluationResult(decision, next_snapshot, deviation)

    clear_since = snapshot.clear_pending_since or observation.captured_at
    due_at = clear_since + timedelta(seconds=configuration.clear_duration_seconds)
    decision = (
        AlertEvaluationDecision.RESOLVE
        if observation.captured_at >= due_at
        else AlertEvaluationDecision.START_CLEAR_PENDING
    )
    next_snapshot = accepted_snapshot(
        snapshot,
        observation,
        trigger_pending_since=None,
        clear_pending_since=(
            None if decision is AlertEvaluationDecision.RESOLVE else clear_since
        ),
        maximum_deviation=maximum_deviation,
    )
    if decision is AlertEvaluationDecision.RESOLVE:
        next_snapshot = replace(
            next_snapshot,
            active_alert_id=None,
            cooldown_until=observation.captured_at
            + timedelta(seconds=configuration.cooldown_seconds),
        )
    return AlertEvaluationResult(decision, next_snapshot, deviation)
