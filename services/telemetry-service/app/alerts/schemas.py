from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.alerts.domain import AlertCondition, AlertSeverity, AlertState


def _persisted_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class AlertRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    severity: AlertSeverity
    node_id: str | None = Field(default=None, max_length=128)
    equipment_id: str | None = Field(default=None, max_length=128)
    channel_id: str | None = Field(default=None, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=36)
    condition: AlertCondition
    trigger_threshold: float
    clear_threshold: float
    minimum_duration_seconds: int = Field(default=0, ge=0, le=86400)
    clear_duration_seconds: int = Field(default=0, ge=0, le=86400)
    debounce_seconds: int = Field(default=0, ge=0, le=86400)
    cooldown_seconds: int = Field(default=0, ge=0, le=604800)
    configuration: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "name",
        "metric",
        "node_id",
        "equipment_id",
        "channel_id",
        "session_id",
        "description",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_hysteresis(self) -> "AlertRuleCreate":
        if (
            self.condition is AlertCondition.THRESHOLD_HIGH
            and self.clear_threshold > self.trigger_threshold
        ):
            raise ValueError(
                "high-threshold clear value must not exceed trigger value"
            )
        if (
            self.condition is AlertCondition.THRESHOLD_LOW
            and self.clear_threshold < self.trigger_threshold
        ):
            raise ValueError(
                "low-threshold clear value must not be below trigger value"
            )
        return self


class AlertRuleReplace(AlertRuleCreate):
    enabled: bool = True


class AlertRuleVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    version: int
    condition: AlertCondition
    trigger_threshold: float
    clear_threshold: float
    minimum_duration_seconds: int
    clear_duration_seconds: int
    debounce_seconds: int
    cooldown_seconds: int
    configuration: dict[str, Any]
    created_by: str
    created_at: datetime

    @field_validator("created_at", mode="before")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        normalized = _persisted_utc(value)
        assert normalized is not None
        return normalized


class AlertRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    description: str | None
    enabled: bool
    severity: AlertSeverity
    node_id: str | None
    equipment_id: str | None
    channel_id: str | None
    metric: str
    session_id: str | None
    current_version: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    version: AlertRuleVersionRead | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        normalized = _persisted_utc(value)
        assert normalized is not None
        return normalized


class AlertRulePage(BaseModel):
    items: list[AlertRuleRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class AlertLifecycleCommand(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    rule_id: str
    rule_version_id: str
    resource_key: str
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    state: AlertState
    severity: AlertSeverity
    trigger_value: float | None
    trigger_threshold: float | None
    clear_threshold: float | None
    maximum_deviation: float
    first_event_id: str
    last_event_id: str
    session_id: str | None
    stage_id: str | None
    binding_id: str | None
    context: dict[str, Any]
    triggered_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    lock_version: int
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "triggered_at",
        "acknowledged_at",
        "resolved_at",
        "closed_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def normalize_timestamps(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return _persisted_utc(value)


class AlertTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_id: str
    event_type: str
    previous_state: AlertState | None
    next_state: AlertState
    actor_id: str
    actor_source: str
    reason: str | None
    idempotency_key: str
    payload: dict[str, Any]
    occurred_at: datetime
    inserted_at: datetime

    @field_validator("occurred_at", "inserted_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        normalized = _persisted_utc(value)
        assert normalized is not None
        return normalized


class AlertEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alert_id: str
    event_id: str
    captured_at: datetime
    value: float | None
    threshold: float | None
    deviation: float
    payload: dict[str, Any]
    created_at: datetime

    @field_validator("captured_at", "created_at", mode="before")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        normalized = _persisted_utc(value)
        assert normalized is not None
        return normalized


class AlertPage(BaseModel):
    items: list[AlertRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class AlertTransitionPage(BaseModel):
    items: list[AlertTransitionRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class AlertEvidencePage(BaseModel):
    items: list[AlertEvidenceRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class AlertLifecycleResponse(BaseModel):
    alert: AlertRead
    transition: AlertTransitionRead
    replayed: bool
