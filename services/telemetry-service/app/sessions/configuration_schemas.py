from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.sessions.schemas import SessionEventRead, SessionRead


class ConfigurationCommand(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = Field(default=None, max_length=2000)
    allow_active_change: bool = False

    @field_validator("actor_id", "actor_source", "reason")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
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


class SessionBindingCreate(ConfigurationCommand):
    node_id: str = Field(default="edge-01", min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    unit: str | None = Field(default=None, max_length=32)
    binding_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("node_id", "equipment_id", "channel_id", "metric", "unit")
    @classmethod
    def normalize_binding_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProductionBindingsCreate(ConfigurationCommand):
    binding_metadata: dict[str, Any] = Field(default_factory=dict)


class SessionBindingRemove(ConfigurationCommand):
    pass


class SessionLimitRuleCreate(BaseModel):
    binding_id: str | None = Field(default=None, max_length=36)
    metric: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=32)
    lower_limit: float | None = None
    upper_limit: float | None = None
    hysteresis: float | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("binding_id", "metric", "unit")
    @classmethod
    def normalize_rule_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_limit_order(self) -> "SessionLimitRuleCreate":
        if (
            self.lower_limit is not None
            and self.upper_limit is not None
            and self.lower_limit > self.upper_limit
        ):
            raise ValueError("lower_limit must not exceed upper_limit")
        return self


class SessionLimitSetCreate(ConfigurationCommand):
    limits: list[SessionLimitRuleCreate] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def reject_duplicate_rules(self) -> "SessionLimitSetCreate":
        identities = [(item.binding_id, item.metric) for item in self.limits]
        if len(identities) != len(set(identities)):
            raise ValueError("limit rules must be unique by binding_id and metric")
        return self


class SessionBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    unit: str | None
    binding_metadata: dict[str, Any]
    activated_at: datetime | None
    released_at: datetime | None
    created_at: datetime


class SessionLimitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    binding_id: str | None
    config_snapshot_id: str | None
    supersedes_limit_id: str | None
    metric: str
    unit: str
    version: int
    lower_limit: float | None
    upper_limit: float | None
    hysteresis: float | None
    duration_seconds: int | None
    payload: dict[str, Any]
    created_by: str
    effective_at: datetime
    created_at: datetime


class SessionConfigSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    version: int
    source: str
    payload: dict[str, Any]
    content_sha256: str
    created_by: str
    captured_at: datetime
    created_at: datetime


class BindingMutationResponse(BaseModel):
    binding: SessionBindingRead
    event: SessionEventRead
    replayed: bool
    active_config_snapshot_id: str | None


class ProductionBindingsResponse(BaseModel):
    bindings: list[SessionBindingRead]
    event: SessionEventRead
    replayed: bool
    active_config_snapshot_id: str | None
    expected_series_count: int


class BindingRemovalResponse(BaseModel):
    binding_id: str
    event: SessionEventRead
    replayed: bool
    active_config_snapshot_id: str | None


class LimitSetMutationResponse(BaseModel):
    version: int
    limits: list[SessionLimitRead]
    event: SessionEventRead
    replayed: bool
    active_config_snapshot_id: str | None


class SessionConfigurationRead(BaseModel):
    session: SessionRead
    bindings: list[SessionBindingRead]
    active_limits: list[SessionLimitRead]
    active_snapshot: SessionConfigSnapshotRead | None
    snapshots: list[SessionConfigSnapshotRead]
