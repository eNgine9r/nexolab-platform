from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EquipmentHealthStatus = Literal["normal", "warning", "alarm", "offline"]
EquipmentLifecycleStatus = Literal["active", "maintenance", "retired"]
SensorSide = Literal["front", "rear"]


class RefrigerationEquipmentCreate(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    location: Annotated[str, Field(min_length=1, max_length=255)]
    laboratory: Annotated[str | None, Field(max_length=128)] = None
    zone: Annotated[str | None, Field(max_length=128)] = None
    node_id: Annotated[str | None, Field(max_length=64)] = None
    equipment_type: Annotated[str, Field(min_length=1, max_length=128)] = "Холодильна вітрина"
    manufacturer: Annotated[str, Field(min_length=1, max_length=128)]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    serial_number: Annotated[str, Field(min_length=1, max_length=128)]
    temperature_class: Annotated[str, Field(min_length=1, max_length=128)]
    installed_at: date | None = None
    serviced_at: date | None = None
    lifecycle_status: EquipmentLifecycleStatus = "active"
    total_sensors: Annotated[int, Field(ge=0, le=48)] = 0

    @field_validator(
        "code",
        "name",
        "location",
        "equipment_type",
        "manufacturer",
        "model",
        "serial_number",
        "temperature_class",
    )
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("laboratory", "zone", "node_id")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_location_hierarchy(self) -> "RefrigerationEquipmentCreate":
        if self.zone is not None and self.laboratory is None:
            raise ValueError("laboratory is required when zone is selected")
        return self


class RefrigerationEquipmentUpdate(RefrigerationEquipmentCreate):
    """Complete, idempotent replacement of editable equipment passport fields."""


class RefrigerationEquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    location: str
    laboratory: str | None
    zone: str | None
    node_id: str | None
    equipment_type: str
    manufacturer: str
    model: str
    serial_number: str
    temperature_class: str
    installed_at: date | None
    serviced_at: date | None
    lifecycle_status: EquipmentLifecycleStatus
    status: EquipmentHealthStatus
    average_temperature_c: float
    min_temperature_c: float
    max_temperature_c: float
    online_sensors: int
    total_sensors: int
    active_alarms: int
    last_seen_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime


class RefrigerationEquipmentListResponse(BaseModel):
    items: list[RefrigerationEquipmentResponse]


class EquipmentNodeOptionResponse(BaseModel):
    node_id: str
    display_name: str
    state: str
    last_seen_at: datetime | None


class EquipmentNodeOptionsResponse(BaseModel):
    items: list[EquipmentNodeOptionResponse]


class SensorPlacementPayload(BaseModel):
    sensor_id: Annotated[str, Field(min_length=1, max_length=128)]
    x: Annotated[float, Field(ge=0.0, le=1.0)]
    y: Annotated[float, Field(ge=0.0, le=1.0)]

    @field_validator("sensor_id")
    @classmethod
    def normalize_sensor_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("sensor_id must not be blank")
        return normalized


class LayoutDraftWrite(BaseModel):
    image_id: str | None = Field(default=None, max_length=36)
    placements: list[SensorPlacementPayload]


class PublishLayoutRequest(BaseModel):
    actor_id: str = Field(min_length=1, max_length=128)

    @field_validator("actor_id")
    @classmethod
    def normalize_actor_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("actor_id must not be blank")
        return normalized


class EquipmentImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    equipment_id: str
    original_filename: str
    media_type: str
    size_bytes: int
    width_px: int
    height_px: int
    checksum_sha256: str
    object_etag: str | None
    created_by: str
    created_at: datetime
    retired_by: str | None = None
    retired_at: datetime | None = None
    content_url: str


class EquipmentImageListResponse(BaseModel):
    items: list[EquipmentImageResponse]


class LayoutDraftResponse(BaseModel):
    id: str
    equipment_id: str
    version: int
    image: EquipmentImageResponse | None
    placements: list[SensorPlacementPayload]
    created_at: datetime
    updated_at: datetime


class LayoutRevisionResponse(BaseModel):
    id: str
    equipment_id: str
    revision: int
    source_draft_version: int
    image: EquipmentImageResponse
    placements: list[SensorPlacementPayload]
    published_by: str
    published_at: datetime


class LayoutHistoryResponse(BaseModel):
    items: list[LayoutRevisionResponse]


class LayoutMutationResponse(BaseModel):
    draft: LayoutDraftResponse
    published: LayoutRevisionResponse | None = None


class SensorBindingWrite(BaseModel):
    channel_id: Annotated[str, Field(min_length=1, max_length=128)]
    label: Annotated[str, Field(min_length=1, max_length=128)]
    side: SensorSide
    shelf: Annotated[int, Field(ge=1, le=4)]
    position: Annotated[int, Field(ge=1, le=6)]

    @field_validator("channel_id", "label")
    @classmethod
    def normalize_binding_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class SensorBindingResponse(BaseModel):
    id: str
    equipment_id: str
    node_id: str
    channel_id: str
    slot_key: str
    label: str
    side: SensorSide
    shelf: int
    position: int
    version: int
    bound_by: str
    bound_at: datetime
    unbound_by: str | None
    unbound_at: datetime | None


class SensorBindingListResponse(BaseModel):
    items: list[SensorBindingResponse]


class SensorBindingMutationResponse(BaseModel):
    equipment: RefrigerationEquipmentResponse
    binding: SensorBindingResponse | None
    draft: LayoutDraftResponse


class AvailableSensorResponse(BaseModel):
    channel_id: str
    metric: str
    unit: str
    latest_value: float | None
    quality: str
    captured_at: datetime
    is_bound: bool
    bound_equipment_id: str | None = None
    bound_slot_key: str | None = None


class AvailableSensorListResponse(BaseModel):
    node_id: str
    items: list[AvailableSensorResponse]


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    expected_version: int | None = None
    actual_version: int | None = None
    issues: list[str] | None = None


class ApiErrorResponse(BaseModel):
    detail: ApiErrorDetail
