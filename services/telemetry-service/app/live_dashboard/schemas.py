from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MAX_DASHBOARD_ITEMS = 64
MAX_DASHBOARD_NAME_LENGTH = 128
MAX_DASHBOARD_DESCRIPTION_LENGTH = 1024
MAX_DASHBOARD_PAGE_SIZE = 100
MAX_DASHBOARD_OFFSET = 10_000
MAX_INVENTORY_PAGE_SIZE = 500
MAX_INVENTORY_OFFSET = 10_000
ALLOWED_REFRESH_SECONDS = frozenset({1, 2, 5, 10, 15, 30, 60})
VIEW_SETTINGS_SCHEMA_VERSION = 1
MAX_VIEW_HIDDEN_ITEMS = 64
MAX_VIEW_ITEM_IDENTITY_LENGTH = 512
MAX_VIEW_CUSTOM_RANGE = timedelta(days=31)


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


class LiveDashboardViewSettings(BaseModel):
    """Saved analysis view of a dashboard (#1666): how the operator last analysed it.

    Device/channel selection, colours and order live in the dashboard items; this adds the view
    state that was not persisted before: hidden series, the history range (preset or custom),
    the zoomed viewport and the chart detail. Every field is optional so the schema can evolve
    additively; unknown future ``schema_version`` values are rejected on write and ignored on read.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int = VIEW_SETTINGS_SCHEMA_VERSION
    hidden_items: list[str] = Field(default_factory=list, max_length=MAX_VIEW_HIDDEN_ITEMS)
    range_kind: Literal["1h", "6h", "24h", "7d", "30d", "custom"] | None = None
    range_from: datetime | None = None
    range_to: datetime | None = None
    viewport_from: datetime | None = None
    viewport_to: datetime | None = None
    density: Literal["auto", 250, 500, 1000, 2500, 5000] | None = None

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != VIEW_SETTINGS_SCHEMA_VERSION:
            raise ValueError(f"unsupported view settings schema_version {value}")
        return value

    @field_validator("hidden_items")
    @classmethod
    def validate_hidden_items(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if not item or len(item) > MAX_VIEW_ITEM_IDENTITY_LENGTH:
                raise ValueError("hidden item identities must be 1..512 characters")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned

    @model_validator(mode="after")
    def validate_ranges(self) -> "LiveDashboardViewSettings":
        if self.range_kind == "custom":
            if self.range_from is None or self.range_to is None:
                raise ValueError("a custom range requires range_from and range_to")
            if self.range_to <= self.range_from:
                raise ValueError("range_to must be after range_from")
            if self.range_to - self.range_from > MAX_VIEW_CUSTOM_RANGE:
                raise ValueError("a custom range may not exceed 31 days")
        elif self.range_from is not None or self.range_to is not None:
            raise ValueError("range_from and range_to are only valid for a custom range")
        if (self.viewport_from is None) != (self.viewport_to is None):
            raise ValueError("viewport_from and viewport_to must be supplied together")
        if (
            self.viewport_from is not None
            and self.viewport_to is not None
            and self.viewport_to <= self.viewport_from
        ):
            raise ValueError("viewport_to must be after viewport_from")
        return self


class LiveDashboardItemWrite(BaseModel):
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=64)
    node_id: str | None = Field(default=None, min_length=1, max_length=128)
    equipment_id: str | None = Field(default=None, min_length=1, max_length=128)
    visualization: VisualizationType = VisualizationType.LINE
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    display_unit: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def validate_observed_scope(self) -> "LiveDashboardItemWrite":
        if (self.node_id is None) != (self.equipment_id is None):
            raise ValueError("node_id and equipment_id must be supplied together")
        return self

    @field_validator("channel_id", "metric", "display_unit", "node_id", "equipment_id", mode="before")
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
    # Omitted = keep the stored view (older clients stay compatible); explicit null = clear it.
    view_settings: LiveDashboardViewSettings | None = None

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
        identities = [(item.node_id, item.equipment_id, item.channel_id, item.metric) for item in self.items]
        if len(identities) != len(set(identities)):
            raise ValueError("dashboard items must use unique channel and metric pairs")
        return self


class LiveDashboardItemResponse(BaseModel):
    id: str
    position: int
    channel_ref_id: str | None
    node_id: str | None = None
    equipment_id: str | None = None
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
    view_settings: LiveDashboardViewSettings | None = None


class LiveDashboardCollectionResponse(BaseModel):
    items: list[LiveDashboardResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class LiveDashboardInventoryLatestResponse(BaseModel):
    event_id: str
    node_id: str
    equipment_id: str
    channel_id: str
    captured_at: datetime
    metric: str
    value: float | None
    unit: str
    quality: str
    source: str
    alarm: str | None
    raw_value: int | None = None
    raw_status: int | None = None
    received_at: datetime


class LiveDashboardInventoryItemResponse(BaseModel):
    channel_ref_id: str | None
    node_id: str
    equipment_id: str
    equipment_name: str
    climate_chamber_id: str | None
    climate_chamber_code: str | None
    climate_chamber_name: str | None
    equipment_type: str
    laboratory: str | None
    zone: str | None
    channel_id: str
    channel_name: str
    metric: str
    native_unit: str
    source: str
    quality: str
    alarm: str | None
    latest: LiveDashboardInventoryLatestResponse | None


class LiveDashboardInventoryCollectionResponse(BaseModel):
    items: list[LiveDashboardInventoryItemResponse]
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
