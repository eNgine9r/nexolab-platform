from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Callable


class AlertCondition(StrEnum):
    HIGH = "high"
    LOW = "low"
    QUALITY = "quality"


class AlertState(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AlertTransition(StrEnum):
    PENDING_STARTED = "pending_started"
    PENDING_CLEARED = "pending_cleared"
    ACTIVATED = "activated"
    OBSERVED = "observed"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"
    IGNORED_DUPLICATE = "ignored_duplicate"
    IGNORED_OUT_OF_ORDER = "ignored_out_of_order"
    IGNORED_COOLDOWN = "ignored_cooldown"


@dataclass(frozen=True, slots=True)
class AlertRule:
    id: str
    organization_id: str
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    condition: AlertCondition
    severity: str
    trigger_threshold: float | None = None
    clear_threshold: float | None = None
    target_quality: str | None = None
    minimum_duration_seconds: int = 0
    cooldown_seconds: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("id", self.id),
            ("organization_id", self.organization_id),
            ("node_id", self.node_id),
            ("equipment_id", self.equipment_id),
            ("channel_id", self.channel_id),
            ("metric", self.metric),
            ("severity", self.severity),
        ):
            if not value.strip():
                raise ValueError(f"{name} is required")
        if self.minimum_duration_seconds < 0:
            raise ValueError("minimum_duration_seconds must be non-negative")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        if self.condition in {AlertCondition.HIGH, AlertCondition.LOW}:
            if self.trigger_threshold is None or self.clear_threshold is None:
                raise ValueError("threshold rules require trigger and clear thresholds")
            if self.target_quality is not None:
                raise ValueError("threshold rules cannot define target_quality")
            if (
                self.condition is AlertCondition.HIGH
                and self.clear_threshold >= self.trigger_threshold
            ):
                raise ValueError("high clear threshold must be lower than trigger")
            if (
                self.condition is AlertCondition.LOW
                and self.clear_threshold <= self.trigger_threshold
            ):
                raise ValueError("low clear threshold must be higher than trigger")
        elif self.condition is AlertCondition.QUALITY:
            if not self.target_quality or not self.target_quality.strip():
                raise ValueError("quality rules require target_quality")
            if self.trigger_threshold is not None or self.clear_threshold is not None:
                raise ValueError("quality rules cannot define numeric thresholds")


@dataclass(frozen=True, slots=True)
class AlertObservation:
    event_id: str
    captured_at: datetime
    value: float | None
    quality: str

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        if not self.quality.strip():
            raise ValueError("quality is required")


@dataclass(frozen=True, slots=True)
class AlertRecord:
    id: str
    rule_id: str
    state: AlertState
    triggered_at: datetime
    first_event_id: str
    last_event_id: str
    trigger_value: float | None
    current_value: float | None
    peak_value: float | None
    current_quality: str
    last_observed_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    acknowledgement_reason: str | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    close_reason: str | None = None

    @property
    def duration_seconds(self) -> float:
        end = self.resolved_at or self.last_observed_at
        return max(0.0, (end - self.triggered_at).total_seconds())


@dataclass(frozen=True, slots=True)
class RuleRuntime:
    pending_since: datetime | None = None
    pending_event_id: str | None = None
    cooldown_until: datetime | None = None
    last_event_id: str | None = None
    last_observed_at: datetime | None = None
    active_alert: AlertRecord | None = None


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    runtime: RuleRuntime
    transitions: tuple[AlertTransition, ...]
    completed_alert: AlertRecord | None = None


def evaluate_observation(
    rule: AlertRule,
    observation: AlertObservation,
    runtime: RuleRuntime,
    *,
    create_alert_id: Callable[[], str],
) -> EvaluationResult:
    if observation.event_id == runtime.last_event_id:
        return EvaluationResult(
            runtime=runtime,
            transitions=(AlertTransition.IGNORED_DUPLICATE,),
        )
    if runtime.last_observed_at is not None and observation.captured_at < runtime.last_observed_at:
        return EvaluationResult(
            runtime=runtime,
            transitions=(AlertTransition.IGNORED_OUT_OF_ORDER,),
        )

    base_runtime = replace(
        runtime,
        last_event_id=observation.event_id,
        last_observed_at=observation.captured_at,
    )
    breach = _is_breach(rule, observation)
    clears = _clears(rule, observation)

    if runtime.active_alert is not None:
        updated = _observe_alert(rule, runtime.active_alert, observation)
        if clears:
            resolved = replace(
                updated,
                state=AlertState.RESOLVED,
                resolved_at=observation.captured_at,
            )
            return EvaluationResult(
                runtime=replace(
                    base_runtime,
                    active_alert=None,
                    pending_since=None,
                    pending_event_id=None,
                    cooldown_until=observation.captured_at
                    + timedelta(seconds=rule.cooldown_seconds),
                ),
                transitions=(AlertTransition.RESOLVED,),
                completed_alert=resolved,
            )
        return EvaluationResult(
            runtime=replace(base_runtime, active_alert=updated),
            transitions=(AlertTransition.OBSERVED,),
        )

    if not breach:
        if runtime.pending_since is None:
            return EvaluationResult(runtime=base_runtime, transitions=())
        return EvaluationResult(
            runtime=replace(
                base_runtime,
                pending_since=None,
                pending_event_id=None,
            ),
            transitions=(AlertTransition.PENDING_CLEARED,),
        )

    if runtime.cooldown_until is not None and observation.captured_at < runtime.cooldown_until:
        return EvaluationResult(
            runtime=replace(
                base_runtime,
                pending_since=None,
                pending_event_id=None,
            ),
            transitions=(AlertTransition.IGNORED_COOLDOWN,),
        )

    pending_since = runtime.pending_since or observation.captured_at
    pending_event_id = runtime.pending_event_id or observation.event_id
    elapsed = (observation.captured_at - pending_since).total_seconds()
    if elapsed < rule.minimum_duration_seconds:
        transition = (
            AlertTransition.PENDING_STARTED
            if runtime.pending_since is None
            else AlertTransition.OBSERVED
        )
        return EvaluationResult(
            runtime=replace(
                base_runtime,
                pending_since=pending_since,
                pending_event_id=pending_event_id,
                cooldown_until=None,
            ),
            transitions=(transition,),
        )

    alert_id = create_alert_id().strip()
    if not alert_id:
        raise ValueError("create_alert_id returned an empty identifier")
    alert = AlertRecord(
        id=alert_id,
        rule_id=rule.id,
        state=AlertState.ACTIVE,
        triggered_at=pending_since,
        first_event_id=pending_event_id,
        last_event_id=observation.event_id,
        trigger_value=observation.value,
        current_value=observation.value,
        peak_value=observation.value,
        current_quality=observation.quality,
        last_observed_at=observation.captured_at,
    )
    return EvaluationResult(
        runtime=replace(
            base_runtime,
            pending_since=None,
            pending_event_id=None,
            cooldown_until=None,
            active_alert=alert,
        ),
        transitions=(AlertTransition.ACTIVATED,),
    )


def acknowledge_alert(
    alert: AlertRecord,
    *,
    actor_subject: str,
    reason: str,
    acknowledged_at: datetime,
) -> AlertRecord:
    if alert.state is not AlertState.ACTIVE:
        raise ValueError("only active alerts can be acknowledged")
    if not actor_subject.strip():
        raise ValueError("actor_subject is required")
    if not reason.strip():
        raise ValueError("acknowledgement reason is required")
    _require_aware(acknowledged_at, "acknowledged_at")
    if acknowledged_at < alert.triggered_at:
        raise ValueError("acknowledged_at cannot precede trigger")
    return replace(
        alert,
        state=AlertState.ACKNOWLEDGED,
        acknowledged_at=acknowledged_at,
        acknowledged_by=actor_subject.strip(),
        acknowledgement_reason=reason.strip(),
    )


def close_alert(
    alert: AlertRecord,
    *,
    actor_subject: str,
    reason: str,
    closed_at: datetime,
) -> AlertRecord:
    if alert.state is not AlertState.RESOLVED:
        raise ValueError("only resolved alerts can be closed")
    if not actor_subject.strip():
        raise ValueError("actor_subject is required")
    if not reason.strip():
        raise ValueError("close reason is required")
    _require_aware(closed_at, "closed_at")
    assert alert.resolved_at is not None
    if closed_at < alert.resolved_at:
        raise ValueError("closed_at cannot precede resolution")
    return replace(
        alert,
        state=AlertState.CLOSED,
        closed_at=closed_at,
        closed_by=actor_subject.strip(),
        close_reason=reason.strip(),
    )


def _is_breach(rule: AlertRule, observation: AlertObservation) -> bool:
    if rule.condition is AlertCondition.QUALITY:
        return observation.quality == rule.target_quality
    if observation.quality != "valid" or observation.value is None:
        return False
    assert rule.trigger_threshold is not None
    if rule.condition is AlertCondition.HIGH:
        return observation.value > rule.trigger_threshold
    return observation.value < rule.trigger_threshold


def _clears(rule: AlertRule, observation: AlertObservation) -> bool:
    if rule.condition is AlertCondition.QUALITY:
        return observation.quality != rule.target_quality
    if observation.quality != "valid" or observation.value is None:
        return False
    assert rule.clear_threshold is not None
    if rule.condition is AlertCondition.HIGH:
        return observation.value <= rule.clear_threshold
    return observation.value >= rule.clear_threshold


def _observe_alert(
    rule: AlertRule,
    alert: AlertRecord,
    observation: AlertObservation,
) -> AlertRecord:
    peak = alert.peak_value
    if observation.value is not None:
        if peak is None:
            peak = observation.value
        elif rule.condition is AlertCondition.HIGH:
            peak = max(peak, observation.value)
        elif rule.condition is AlertCondition.LOW:
            peak = min(peak, observation.value)
    return replace(
        alert,
        last_event_id=observation.event_id,
        current_value=observation.value,
        peak_value=peak,
        current_quality=observation.quality,
        last_observed_at=observation.captured_at,
    )


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
