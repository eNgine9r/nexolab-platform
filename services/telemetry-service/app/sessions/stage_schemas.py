from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sessions.domain import SessionStage
from app.sessions.schemas import SessionEventRead, SessionRead


class StageDefinitionCreate(BaseModel):
    stage_type: SessionStage
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    planned_duration_seconds: int | None = Field(default=None, ge=1)

    @field_validator("name", "description")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class StagePlanCreate(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stages: list[StageDefinitionCreate] = Field(min_length=1, max_length=32)

    @field_validator("actor_id", "actor_source")
    @classmethod
    def normalize_actor_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class StageAdvanceRequest(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)
    actor_source: str = Field(default="dashboard", min_length=1, max_length=64)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("actor_id", "actor_source", "reason")
    @classmethod
    def normalize_command_text(cls, value: str | None) -> str | None:
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


class SessionStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    sequence_index: int
    stage_type: str
    name: str
    description: str | None
    planned_duration_seconds: int | None
    entered_at: datetime | None
    exited_at: datetime | None
    created_at: datetime


class StageTransitionRead(BaseModel):
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


class StagePlanMutationResponse(BaseModel):
    stages: list[SessionStageRead]
    event: SessionEventRead
    replayed: bool


class StageAdvanceResponse(BaseModel):
    session: SessionRead
    current_stage: SessionStageRead
    transition: StageTransitionRead
    event: SessionEventRead
    replayed: bool
