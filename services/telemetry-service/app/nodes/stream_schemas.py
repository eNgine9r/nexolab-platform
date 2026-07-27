from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


NodeAvailabilityRead = Literal["online", "offline", "stale", "unknown"]


class NodeHealthRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    node_record_id: str
    node_sequence: int
    health: Literal["healthy", "degraded"]
    uptime_seconds: int
    queue_depth: int
    samples_total: int
    software_version: str
    device_mode: str
    last_sample_at: datetime | None
    last_publish_at: datetime | None
    last_error: str | None
    captured_at: datetime
    received_at: datetime
    inserted_at: datetime


class NodeStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    event_id: str
    node_record_id: str
    node_sequence: int
    status: Literal["online", "offline"]
    reason: str
    software_version: str | None
    graceful: bool
    captured_at: datetime
    received_at: datetime
    inserted_at: datetime


class NodeOperationalStateRead(BaseModel):
    node_id: str
    availability: NodeAvailabilityRead
    stale_after_seconds: int
    heartbeat_age_seconds: float | None
    degraded_reason: str | None
    latest_health: NodeHealthRead | None
    latest_status: NodeStatusRead | None
