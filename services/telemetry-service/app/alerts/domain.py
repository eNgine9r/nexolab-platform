from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class AlertSeverity(StrEnum):
    INFORMATION = "information"
    WARNING = "warning"
    ALARM = "alarm"
    CRITICAL = "critical"
    SYSTEM = "system"


class AlertState(StrEnum):
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AlertCondition(StrEnum):
    THRESHOLD_HIGH = "threshold_high"
    THRESHOLD_LOW = "threshold_low"


class AlertEvaluationDecision(StrEnum):
    NONE = "none"
    START_TRIGGER_PENDING = "start_trigger_pending"
    RESET_TRIGGER_PENDING = "reset_trigger_pending"
    TRIGGER = "trigger"
    START_CLEAR_PENDING = "start_clear_pending"
    RESET_CLEAR_PENDING = "reset_clear_pending"
    RESOLVE = "resolve"
    IGNORE_DUPLICATE = "ignore_duplicate"
    IGNORE_OUT_OF_ORDER = "ignore_out_of_order"
    IGNORE_COOLDOWN = "ignore_cooldown"
    IGNORE_INVALID_VALUE = "ignore_invalid_value"


@dataclass(frozen=True, slots=True)
class AlertRuleConfiguration:
    condition: AlertCondition
    trigger_threshold: float
    clear_threshold: float
    minimum_duration_seconds: int = 0
    clear_duration_seconds: int = 0
    debounce_seconds: int = 0
    cooldown_seconds: int = 0

    def __post_init__(self) -> None:
        for name in (
            "minimum_duration_seconds",
            "clear_duration_seconds",
            "debounce_seconds",
            "cooldown_seconds",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.condition is AlertCondition.THRESHOLD_HIGH:
            if self.clear_threshold > self.trigger_threshold:
                raise ValueError(
                    "high-threshold clear value must not exceed trigger value"
                )
        elif self.condition is AlertCondition.THRESHOLD_LOW:
            if self.clear_threshold < self.trigger_threshold:
                raise ValueError(
                    "low-threshold clear value must not be below trigger value"
                )

    @property
    def trigger_duration_seconds(self) -> int:
        return max(self.minimum_duration_seconds, self.debounce_seconds)

    def is_triggered(self, value: float) -> bool:
        if self.condition is AlertCondition.THRESHOLD_HIGH:
            return value >= self.trigger_threshold
        return value <= self.trigger_threshold

    def is_clear(self, value: float) -> bool:
        if self.condition is AlertCondition.THRESHOLD_HIGH:
            return value <= self.clear_threshold
        return value >= self.clear_threshold

    def deviation(self, value: float) -> float:
        if self.condition is AlertCondition.THRESHOLD_HIGH:
            return max(0.0, value - self.trigger_threshold)
        return max(0.0, self.trigger_threshold - value)


@dataclass(frozen=True, slots=True)
class TelemetryObservation:
    event_id: str
    captured_at: datetime
    value: float | None

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise ValueError("event_id is required")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class AlertEvaluationSnapshot:
    last_event_id: str | None = None
    last_captured_at: datetime | None = None
    trigger_pending_since: datetime | None = None
    clear_pending_since: datetime | None = None
    active_alert_id: str | None = None
    cooldown_until: datetime | None = None
    last_value: float | None = None
    maximum_deviation: float = 0.0


@dataclass(frozen=True, slots=True)
class AlertEvaluationResult:
    decision: AlertEvaluationDecision
    snapshot: AlertEvaluationSnapshot
    deviation: float = 0.0


def accepted_snapshot(
    snapshot: AlertEvaluationSnapshot,
    observation: TelemetryObservation,
    *,
    trigger_pending_since: datetime | None,
    clear_pending_since: datetime | None,
    maximum_deviation: float,
) -> AlertEvaluationSnapshot:
    return replace(
        snapshot,
        last_event_id=observation.event_id,
        last_captured_at=observation.captured_at,
        last_value=observation.value,
        trigger_pending_since=trigger_pending_since,
        clear_pending_since=clear_pending_since,
        maximum_deviation=maximum_deviation,
    )
