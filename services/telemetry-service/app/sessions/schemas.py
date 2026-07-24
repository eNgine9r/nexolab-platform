from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sessions.domain import SessionState


class SessionCreate(BaseModel):
    session_number: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    test_object: str = Field(min_length=1, max_length=256)
    node_id: str = Field(default="edge-01", min_length=1, max_length=128)
    customer: str | None = Field(default=None, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=128)
    standard: str | None = Field(default=None, max_length=256)
    method: str | None = Field(default=None, max_length=256)
    operator_id: str | None = Field(default=None, max_length=128)
    responsible_engineer_id: str | None = Field(default=None, max_length=128)
    metadata_payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator(
        "session_number",
        "title",
        "test_object",
        "node_id",
        "actor_id",
        "actor_source",
    )
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator(
        "reason",
        "customer",
        "model",
        "serial_number",
        "standard",
        "method",
        "operator_id",
        "responsible_engineer_id",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
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


class SessionPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    customer: str | None = Field(default=None, max_length=256)
    test_object: str | None = Field(default=None, min_length=1, max_length=256)
    model: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=128)
    standard: str | None = Field(default=None, max_length=256)
    method: str | None = Field(default=None, max_length=256)
    operator_id: str | None = Field(default=None, max_length=128)
    responsible_engineer_id: str | None = Field(default=None, max_length=128)
    metadata_payload: dict[str, Any] | None = None

    @field_validator(
        "title",
        "customer",
        "test_object",
        "model",
        "serial_number",
        "standard",
        "method",
        "operator_id",
        "responsible_engineer_id",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SessionTransitionRequest(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("actor_id", "actor_source")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("reason")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
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


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_number: str
    node_id: str
    state: SessionState
    title: str
    customer: str | None
    test_object: str
    model: str | None
    serial_number: str | None
    standard: str | None
    method: str | None
    operator_id: str | None
    responsible_engineer_id: str | None
    metadata_payload: dict[str, Any]
    current_stage_id: str | None
    active_config_snapshot_id: str | None
    active_limit_version: int | None
    lock_version: int
    prepared_at: datetime | None
    started_at: datetime | None
    paused_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SessionEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    event_type: str
    previous_state: SessionState | None
    next_state: SessionState | None
    actor_id: str
    actor_source: str
    reason: str | None
    payload: dict[str, Any]
    idempotency_key: str
    occurred_at: datetime
    inserted_at: datetime


class SessionPage(BaseModel):
    items: list[SessionRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class SessionTransitionResponse(BaseModel):
    session: SessionRead
    event: SessionEventRead
    replayed: bool


class SessionEventsPage(BaseModel):
    items: list[SessionEventRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None
