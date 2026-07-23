from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Quality = Literal["valid", "sensor_error", "communication_error", "unknown"]
Alarm = Literal["low", "high"]


class TelemetryEvent(BaseModel):
    """Canonical NEXOLAB telemetry event, version 1."""

    model_config = ConfigDict(extra="allow")

    event_id: UUID
    node_id: str = Field(min_length=1, max_length=128)
    captured_at: AwareDatetime
    metric: str = Field(min_length=1, max_length=128)
    value: float | None
    unit: str = Field(min_length=1, max_length=32)
    quality: Quality
    source: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    channel_id: str = Field(min_length=1, max_length=128)
    alarm: Alarm | None = None
    raw_value: int | None = None
    raw_status: int | None = None

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_value_quality(self) -> "TelemetryEvent":
        if self.quality == "valid" and self.value is None:
            raise ValueError("valid telemetry requires a numeric value")
        return self

    def normalized_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["event_id"] = str(self.event_id)
        return payload
