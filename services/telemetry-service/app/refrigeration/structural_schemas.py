from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.refrigeration.schemas import (
    EquipmentImageResponse,
    LayoutDraftResponse,
    RefrigerationEquipmentResponse,
    SensorBindingResponse,
)


StructuralSampleState = Literal["known", "stale", "unknown"]


class StructuralChannelResponse(BaseModel):
    channel_id: str
    metric: str
    unit: str
    latest_value: float | None
    quality: str
    captured_at: datetime | None
    sample_state: StructuralSampleState
    is_bound: bool
    bound_equipment_id: str | None = None
    bound_slot_key: str | None = None


class RefrigerationStructuralSnapshotResponse(BaseModel):
    equipment: RefrigerationEquipmentResponse
    active_image: EquipmentImageResponse | None
    layout: LayoutDraftResponse
    layout_revision: int
    placements_count: int
    bindings: list[SensorBindingResponse]
    channels: list[StructuralChannelResponse]
    generated_at: datetime
