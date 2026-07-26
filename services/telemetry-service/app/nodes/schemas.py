from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.nodes.domain import ClockStatus, NodeState


class NodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    node_id: str
    display_name: str
    state: NodeState
    state_reason: str | None
    clock_warning_ms: int
    clock_critical_ms: int
    last_seen_at: datetime | None
    last_clock_offset_ms: int | None
    clock_status: ClockStatus
    clock_observed_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class NodeCredentialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    node_record_id: str
    generation: int
    secret_fingerprint: str
    issued_by: str
    issued_at: datetime
    revoked_at: datetime | None


class ProvisionNodeRequest(BaseModel):
    node_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    clock_warning_ms: int = Field(default=30_000, gt=0)
    clock_critical_ms: int = Field(default=120_000, gt=0)


class ProvisionNodeResponse(BaseModel):
    node: NodeRead
    credential: NodeCredentialRead
    provisioning_secret: str | None
    replayed: bool


class NodeStateChangeRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1024)


class RotateNodeCredentialRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1024)


class RotateNodeCredentialResponse(BaseModel):
    node: NodeRead
    credential: NodeCredentialRead
    provisioning_secret: str | None
    replayed: bool
