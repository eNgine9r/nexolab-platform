from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


EquipmentStatus = Literal["normal", "warning", "alarm", "offline"]


class RefrigerationEquipmentCreate(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=128)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    location: Annotated[str, Field(min_length=1, max_length=255)]
    equipment_type: Annotated[str, Field(min_length=1, max_length=128)] = "Холодильна вітрина"
    manufacturer: Annotated[str, Field(min_length=1, max_length=128)]
    model: Annotated[str, Field(min_length=1, max_length=128)]
    serial_number: Annotated[str, Field(min_length=1, max_length=128)]
    temperature_class: Annotated[str, Field(min_length=1, max_length=128)]
    installed_at: date | None = None
    serviced_at: date | None = None
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


class RefrigerationEquipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    location: str
    equipment_type: str
    manufacturer: str
    model: str
    serial_number: str
    temperature_class: str
    installed_at: date | None
    serviced_at: date | None
    status: EquipmentStatus
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
    content_url: str


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


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    expected_version: int | None = None
    actual_version: int | None = None
    issues: list[str] | None = None


class ApiErrorResponse(BaseModel):
    detail: ApiErrorDetail
