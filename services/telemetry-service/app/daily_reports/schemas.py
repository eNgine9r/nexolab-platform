from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.daily_reports.domain import (
    DEFAULT_ANALYSIS_WINDOW_MINUTES,
    DEFAULT_REPORT_HOUR,
    DEFAULT_REPORT_MINUTE,
    DEFAULT_TIMEZONE,
    validate_timezone,
    validate_weekdays,
)


class TelemetryIdentity(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=128)

    @field_validator("node_id", "equipment_id", "channel_id", "metric")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identity fields must not be blank")
        return normalized

    def series_key(self) -> tuple[str, str, str, str]:
        return (self.node_id, self.equipment_id, self.channel_id, self.metric)


class DailyReportProfileWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    equipment_id: str = Field(min_length=1, max_length=36)
    enabled: bool = True
    timezone: str = Field(default=DEFAULT_TIMEZONE, min_length=1, max_length=64)
    report_hour: int = Field(default=DEFAULT_REPORT_HOUR, ge=0, le=23)
    report_minute: int = Field(default=DEFAULT_REPORT_MINUTE, ge=0, le=59)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)
    analysis_window_minutes: int = Field(
        default=DEFAULT_ANALYSIS_WINDOW_MINUTES,
        ge=1,
        le=10_080,
    )
    m_packet_channels: list[TelemetryIdentity] = Field(min_length=1, max_length=256)
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    energy_source: TelemetryIdentity | None = None

    @field_validator("name", "equipment_id")
    @classmethod
    def strip_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        return validate_timezone(value)

    @field_validator("weekdays")
    @classmethod
    def valid_weekdays(cls, value: list[int]) -> list[int]:
        return list(validate_weekdays(value))

    @model_validator(mode="after")
    def validate_profile(self) -> "DailyReportProfileWrite":
        keys = [item.series_key() for item in self.m_packet_channels]
        if len(keys) != len(set(keys)):
            raise ValueError("m_packet_channels must not contain duplicate telemetry identities")
        if (
            self.temperature_min_c is not None
            and self.temperature_max_c is not None
            and self.temperature_min_c >= self.temperature_max_c
        ):
            raise ValueError("temperature_min_c must be lower than temperature_max_c")
        return self


class DailyReportProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    equipment_id: str
    name: str
    enabled: bool
    timezone: str
    report_hour: int
    report_minute: int
    weekdays: list[int]
    analysis_window_minutes: int
    m_packet_channels: list[dict[str, Any]]
    temperature_min_c: float | None
    temperature_max_c: float | None
    energy_source: dict[str, Any] | None
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class DailyReportProfilePage(BaseModel):
    items: list[DailyReportProfileRead]
    count: int


class DailyReportGenerateRequest(BaseModel):
    local_report_date: date | None = None
    reason: str | None = Field(default=None, max_length=1024)


class DailyReportSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    profile_id: str
    equipment_id: str
    local_report_date: date
    scheduled_for: datetime
    window_start: datetime
    window_end: datetime
    timezone: str
    status: str
    schema_version: str
    payload: dict[str, Any]
    payload_sha256: str
    generated_by: str
    generated_at: datetime
    created_at: datetime


class DailyReportGenerationResponse(DailyReportSnapshotRead):
    replayed: bool


class DailyReportMiniAppReadRequest(BaseModel):
    identity_id: UUID


class DailyReportSnapshotPage(BaseModel):
    items: list[DailyReportSnapshotRead]
    count: int
    limit: int
    offset: int
    next_offset: int | None


class DailyReportSchedulerStatus(BaseModel):
    enabled: bool
    running: bool
    last_run_at: datetime | None
    last_generated_count: int
    next_scheduled_for: datetime | None
