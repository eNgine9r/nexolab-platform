from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sessions.audit_contract import validate_actor_source
from app.sessions.schemas import SessionEventRead


class SessionNoteCreate(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stage_id: str | None = Field(default=None, max_length=36)
    body: str = Field(min_length=1, max_length=10000)
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("actor_id", "stage_id", "body", "reason")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("actor_source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        return validate_actor_source(value)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class SessionNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    stage_id: str | None
    author_id: str
    body: str
    created_at: datetime


class SessionNoteMutationResponse(BaseModel):
    note: SessionNoteRead
    event: SessionEventRead
    replayed: bool


class SessionNotesPage(BaseModel):
    items: list[SessionNoteRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str | None
    session_event_id: str | None
    actor_id: str
    actor_source: str
    action: str
    canonical_action: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    occurred_at: datetime
    inserted_at: datetime


class AuditEntriesPage(BaseModel):
    items: list[AuditEntryRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None
