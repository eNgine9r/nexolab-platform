from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_DASHBOARD_ITEMS = 64
MAX_DASHBOARD_NAME_LENGTH = 128
MAX_DASHBOARD_DESCRIPTION_LENGTH = 1024
MAX_DASHBOARD_PAGE_SIZE = 100
MAX_DASHBOARD_OFFSET = 10_000
ALLOWED_REFRESH_SECONDS = frozenset({1, 2, 5, 10, 15, 30, 60})


class VisualizationType(StrEnum):
    LINE = "line"
    AREA = "area"
    GAUGE = "gauge"
    VALUE = "value"


class TimeWindow(StrEnum):
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    THIRTY_MINUTES = "30m"
    ONE_HOUR = "1h"
    SIX_HOURS = "6h"
    TWELVE_HOURS = "12h"
    ONE_DAY = "24h"
    SEVEN_DAYS = "7d"


class DashboardStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class LiveDashboardItemWrite(BaseModel):
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=64)
    visualization: VisualizationType = VisualizationType.LINE
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    display_unit: str | None = Field(default=None, max_length=32)

    @field_validator("channel_id", "metric", "display_unit", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class LiveDashboardWrite(BaseModel):
    name: str = Field(min_length=1, max_length=MAX_DASHBOARD_NAME_LENGTH)
    description: str | None = Field(
        default=None,
        max_length=MAX_DASHBOARD_DESCRIPTION_LENGTH,
    )
    refresh_seconds: int = 5
    time_window: TimeWindow = TimeWindow.FIFTEEN_MINUTES
    items: list[LiveDashboardItemWrite] = Field(
        default_factory=list,
        max_length=MAX_DASHBOARD_ITEMS,
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("dashboard name is required")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("refresh_seconds")
    @classmethod
    def validate_refresh_seconds(cls, value: int) -> int:
        if value not in ALLOWED_REFRESH_SECONDS:
            allowed = ", ".join(str(item) for item in sorted(ALLOWED_REFRESH_SECONDS))
            raise ValueError(f"refresh_seconds must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def validate_unique_items(self) -> "LiveDashboardWrite":
        identities = [(item.channel_id, item.metric) for item in self.items]
        if len(identities) != len(set(identities)):
            raise ValueError("dashboard items must use unique channel and metric pairs")
        return self


class LiveDashboardItemResponse(BaseModel):
    id: str
    position: int
    channel_ref_id: str
    channel_id: str
    metric: str
    native_unit: str
    visualization: VisualizationType
    color: str | None
    display_unit: str | None


class LiveDashboardResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    description: str | None
    owner_subject: str
    refresh_seconds: int
    time_window: TimeWindow
    version: int
    status: DashboardStatus
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    archived_by: str | None
    archived_at: datetime | None
    items: list[LiveDashboardItemResponse]


class LiveDashboardCollectionResponse(BaseModel):
    items: list[LiveDashboardResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    expected_version: int | None = None
    actual_version: int | None = None
    issues: list[str] | None = None


class ApiErrorResponse(BaseModel):
    detail: ApiErrorDetail
