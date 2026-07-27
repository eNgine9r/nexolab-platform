from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.nodes.domain import normalize_node_id


NodeHealthState = Literal["healthy", "degraded"]
NodeAvailability = Literal["online", "offline"]


class NodeStreamEvent(BaseModel):
    """Common immutable identity for version 1 node operational streams."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    event_id: UUID
    node_id: str = Field(min_length=1, max_length=64)
    captured_at: AwareDatetime
    node_sequence: int = Field(ge=1)

    @field_validator("node_id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return normalize_node_id(value)

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    def normalized_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["event_id"] = str(self.event_id)
        return payload


class NodeHealthEvent(NodeStreamEvent):
    """Periodic operational snapshot emitted by one edge node."""

    health: NodeHealthState
    uptime_seconds: int = Field(ge=0)
    queue_depth: int = Field(ge=0)
    samples_total: int = Field(ge=0)
    software_version: str = Field(min_length=1, max_length=64)
    device_mode: str = Field(min_length=1, max_length=64)
    last_sample_at: AwareDatetime | None = None
    last_publish_at: AwareDatetime | None = None
    last_error: str | None = Field(default=None, max_length=2048)

    @field_validator("last_sample_at", "last_publish_at")
    @classmethod
    def normalize_optional_timestamp(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_health_reason(self) -> "NodeHealthEvent":
        if self.health == "healthy" and self.last_error is not None:
            raise ValueError("healthy node health cannot include last_error")
        if self.health == "degraded" and not (self.last_error or "").strip():
            raise ValueError("degraded node health requires last_error")
        return self


class NodeStatusEvent(NodeStreamEvent):
    """Retained availability transition, including MQTT Last Will offline state."""

    status: NodeAvailability
    reason: str = Field(min_length=1, max_length=1024)
    software_version: str | None = Field(default=None, min_length=1, max_length=64)
    graceful: bool

    @model_validator(mode="after")
    def validate_retained_semantics(self) -> "NodeStatusEvent":
        if self.status == "online" and not self.graceful:
            raise ValueError("online status must be an explicit graceful publish")
        return self
