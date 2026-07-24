from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    error: ApiErrorDetail
