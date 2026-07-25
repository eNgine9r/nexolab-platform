from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.alerts.domain import (
    AlertCondition,
    AlertObservation,
    AlertRule,
    AlertState,
    AlertTransition,
    RuleRuntime,
    acknowledge_alert,
    close_alert,
    evaluate_observation,
)


BASE = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)


def high_rule(**overrides: object) -> AlertRule:
    values: dict[str, object] = {
        "id": "rule-high",
        "organization_id": "org-1",
        "node_id": "edge-01",
        "equipment_id": "K106",
        "channel_id": "106-03",
        "metric": "temperature.probe",
        "condition": AlertCondition.HIGH,
        "severity": "critical",
        "trigger_threshold": 8.0,
        "clear_threshold": 7.5,
        "minimum_duration_seconds": 60,
        "cooldown_seconds": 120,
    }
    values.update(overrides)
    return AlertRule(**values)  # type: ignore[arg-type]


def observation(
    second: int,
    *,
    value: float | None,
    quality: str = "valid",
    event_id: str | None = None,
) -> AlertObservation:
    return AlertObservation(
        event_id=event_id or f"event-{second}",
        captured_at=BASE + timedelta(seconds=second),
        value=value,
        quality=quality,
    )


def evaluate(
    rule: AlertRule,
    item: AlertObservation,
    runtime: RuleRuntime,
    alert_id: str = "alert-1",
):
    return evaluate_observation(
        rule,
        item,
        runtime,
        create_alert_id=lambda: alert_id,
    )


def test_short_spike_does_not_activate_alert() -> None:
    first = evaluate(high_rule(), observation(0, value=8.2), RuleRuntime())
    cleared = evaluate(high_rule(), observation(30, value=7.4), first.runtime)

    assert first.transitions == (AlertTransition.PENDING_STARTED,)
    assert first.runtime.pending_since == BASE
    assert cleared.transitions == (AlertTransition.PENDING_CLEARED,)
    assert cleared.runtime.pending_since is None
    assert cleared.runtime.active_alert is None


def test_minimum_duration_activates_from_first_breach() -> None:
    first = evaluate(high_rule(), observation(0, value=8.1), RuleRuntime())
    active = evaluate(high_rule(), observation(60, value=8.4), first.runtime)

    assert active.transitions == (AlertTransition.ACTIVATED,)
    assert active.runtime.active_alert is not None
    assert active.runtime.active_alert.triggered_at == BASE
    assert active.runtime.active_alert.first_event_id == "event-0"
    assert active.runtime.active_alert.last_event_id == "event-60"
    assert active.runtime.active_alert.trigger_value == 8.4


def test_hysteresis_tracks_peak_and_resolves_only_at_clear_threshold() -> None:
    first = evaluate(high_rule(minimum_duration_seconds=0), observation(0, value=8.2), RuleRuntime())
    assert first.runtime.active_alert is not None

    still_active = evaluate(high_rule(minimum_duration_seconds=0), observation(10, value=7.8), first.runtime)
    peak = evaluate(high_rule(minimum_duration_seconds=0), observation(20, value=9.1), still_active.runtime)
    resolved = evaluate(high_rule(minimum_duration_seconds=0), observation(30, value=7.5), peak.runtime)

    assert still_active.runtime.active_alert is not None
    assert still_active.runtime.active_alert.state is AlertState.ACTIVE
    assert peak.runtime.active_alert is not None
    assert peak.runtime.active_alert.peak_value == 9.1
    assert resolved.transitions == (AlertTransition.RESOLVED,)
    assert resolved.runtime.active_alert is None
    assert resolved.completed_alert is not None
    assert resolved.completed_alert.state is AlertState.RESOLVED
    assert resolved.completed_alert.duration_seconds == 30


def test_acknowledgement_does_not_resolve_active_condition() -> None:
    active = evaluate(high_rule(minimum_duration_seconds=0), observation(0, value=8.2), RuleRuntime())
    assert active.runtime.active_alert is not None

    acknowledged = acknowledge_alert(
        active.runtime.active_alert,
        actor_subject="operator-1",
        reason="Equipment inspected",
        acknowledged_at=BASE + timedelta(seconds=5),
    )
    runtime = RuleRuntime(
        last_event_id=active.runtime.last_event_id,
        last_observed_at=active.runtime.last_observed_at,
        active_alert=acknowledged,
    )
    observed = evaluate(high_rule(minimum_duration_seconds=0), observation(10, value=8.4), runtime)

    assert acknowledged.state is AlertState.ACKNOWLEDGED
    assert acknowledged.acknowledged_by == "operator-1"
    assert observed.runtime.active_alert is not None
    assert observed.runtime.active_alert.state is AlertState.ACKNOWLEDGED


def test_cooldown_blocks_immediate_retrigger_then_allows_new_alert() -> None:
    rule = high_rule(minimum_duration_seconds=0, cooldown_seconds=120)
    active = evaluate(rule, observation(0, value=8.2), RuleRuntime())
    resolved = evaluate(rule, observation(10, value=7.5), active.runtime)

    blocked = evaluate(rule, observation(20, value=8.3), resolved.runtime, alert_id="alert-2")
    retriggered = evaluate(rule, observation(130, value=8.5), blocked.runtime, alert_id="alert-2")

    assert blocked.transitions == (AlertTransition.IGNORED_COOLDOWN,)
    assert blocked.runtime.active_alert is None
    assert retriggered.transitions == (AlertTransition.ACTIVATED,)
    assert retriggered.runtime.active_alert is not None
    assert retriggered.runtime.active_alert.id == "alert-2"


def test_quality_fault_rule_activates_and_resolves() -> None:
    rule = AlertRule(
        id="rule-quality",
        organization_id="org-1",
        node_id="edge-01",
        equipment_id="K106",
        channel_id="106-03",
        metric="temperature.probe",
        condition=AlertCondition.QUALITY,
        severity="alarm",
        target_quality="sensor_error",
        minimum_duration_seconds=0,
    )

    active = evaluate(rule, observation(0, value=None, quality="sensor_error"), RuleRuntime())
    resolved = evaluate(rule, observation(10, value=3.2, quality="valid"), active.runtime)

    assert active.runtime.active_alert is not None
    assert active.runtime.active_alert.current_quality == "sensor_error"
    assert resolved.completed_alert is not None
    assert resolved.completed_alert.state is AlertState.RESOLVED


def test_duplicate_and_older_observations_are_ignored() -> None:
    first = evaluate(high_rule(), observation(10, value=8.2), RuleRuntime())
    duplicate = evaluate(
        high_rule(),
        observation(20, value=9.0, event_id="event-10"),
        first.runtime,
    )
    older = evaluate(high_rule(), observation(5, value=9.0), first.runtime)

    assert duplicate.transitions == (AlertTransition.IGNORED_DUPLICATE,)
    assert duplicate.runtime == first.runtime
    assert older.transitions == (AlertTransition.IGNORED_OUT_OF_ORDER,)
    assert older.runtime == first.runtime


def test_only_resolved_alert_can_be_closed() -> None:
    active = evaluate(high_rule(minimum_duration_seconds=0), observation(0, value=8.2), RuleRuntime())
    assert active.runtime.active_alert is not None
    with pytest.raises(ValueError, match="only resolved"):
        close_alert(
            active.runtime.active_alert,
            actor_subject="operator-1",
            reason="Reviewed",
            closed_at=BASE + timedelta(seconds=2),
        )

    resolved = evaluate(
        high_rule(minimum_duration_seconds=0),
        observation(10, value=7.5),
        active.runtime,
    ).completed_alert
    assert resolved is not None
    closed = close_alert(
        resolved,
        actor_subject="operator-1",
        reason="Corrective action complete",
        closed_at=BASE + timedelta(seconds=20),
    )

    assert closed.state is AlertState.CLOSED
    assert closed.closed_by == "operator-1"


def test_rule_validation_requires_real_hysteresis() -> None:
    with pytest.raises(ValueError, match="high clear threshold"):
        high_rule(clear_threshold=8.0)
    with pytest.raises(ValueError, match="target_quality"):
        high_rule(target_quality="sensor_error")
