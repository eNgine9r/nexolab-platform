from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sessions.domain import SessionStage as SessionStageType
from app.sessions.schemas import SessionEventRead


class AuditCommand(BaseModel):
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


class StageAdvanceRequest(AuditCommand):
    sequence_index: int = Field(ge=0)
    stage_type: SessionStageType
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    planned_duration_seconds: int | None = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def normalize_stage_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_stage_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SessionNoteCreate(AuditCommand):
    stage_id: str | None = Field(default=None, max_length=36)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("stage_id")
    @classmethod
    def normalize_stage_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("body")
    @classmethod
    def normalize_note_body(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("body must not be blank")
        return normalized


class SessionStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    sequence_index: int
    stage_type: SessionStageType
    name: str
    description: str | None
    planned_duration_seconds: int | None
    entered_at: datetime | None
    exited_at: datetime | None
    created_at: datetime


class SessionStageTransitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    session_event_id: str
    from_stage_id: str | None
    to_stage_id: str
    from_sequence_index: int | None
    to_sequence_index: int
    actor_id: str
    reason: str | None
    occurred_at: datetime
    inserted_at: datetime


class SessionNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    stage_id: str | None
    author_id: str
    body: str
    created_at: datetime


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str | None
    session_event_id: str | None
    actor_id: str
    actor_source: str
    action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    occurred_at: datetime
    inserted_at: datetime


class StageAdvanceResponse(BaseModel):
    stage: SessionStageRead
    transition: SessionStageTransitionRead
    event: SessionEventRead
    replayed: bool


class SessionNoteResponse(BaseModel):
    note: SessionNoteRead
    event: SessionEventRead
    replayed: bool


class SessionNotesPage(BaseModel):
    items: list[SessionNoteRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class SessionAuditPage(BaseModel):
    items: list[AuditLogRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None
