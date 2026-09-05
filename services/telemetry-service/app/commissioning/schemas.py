from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

CommissioningLifecycle = Literal[
    "draft", "ready_for_preflight", "verified", "pending_activation", "active",
    "activation_failed", "rolled_back", "blocked", "unsupported", "cancelled",
]


class SupportedDeviceProfileResponse(BaseModel):
    id: str
    version: str
    device_family: str
    device_class: str
    manufacturer: str
    models: list[str]
    display_name: str
    transport_kind: Literal["modbus_rtu"]
    capability_status: Literal[
        "repository_supported",
        "repository_supported_hardware_evidenced",
    ]
    evidence_note: str
    read_only: Literal[True] = True


class SupportedDeviceProfileListResponse(BaseModel):
    items: list[SupportedDeviceProfileResponse]


class CommissioningSessionWrite(BaseModel):
    device_class: str = Field(min_length=1, max_length=64)
    manufacturer: str = Field(min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=128)
    profile_id: str | None = Field(default=None, max_length=128)
    node_id: str | None = Field(default=None, max_length=64)
    bus_id: str | None = Field(default=None, max_length=64)
    stable_transport_identifier: str | None = Field(default=None, max_length=255)
    unit_id: int | None = Field(default=None, ge=1, le=247)
    ip_address: str | None = Field(default=None, max_length=45)
    target_equipment_key: str | None = Field(default=None, max_length=255)

    @field_validator("device_class", "manufacturer", "model")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("value must contain non-whitespace characters")
        return normalized

    @field_validator(
        "profile_id",
        "node_id",
        "bus_id",
        "stable_transport_identifier",
        "ip_address",
        "target_equipment_key",
    )
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None


class CommissioningSessionPatch(BaseModel):
    device_class: str | None = Field(default=None, min_length=1, max_length=64)
    manufacturer: str | None = Field(default=None, min_length=1, max_length=128)
    model: str | None = Field(default=None, min_length=1, max_length=128)
    profile_id: str | None = Field(default=None, max_length=128)
    node_id: str | None = Field(default=None, max_length=64)
    bus_id: str | None = Field(default=None, max_length=64)
    stable_transport_identifier: str | None = Field(default=None, max_length=255)
    unit_id: int | None = Field(default=None, ge=1, le=247)
    ip_address: str | None = Field(default=None, max_length=45)
    target_equipment_key: str | None = Field(default=None, max_length=255)

    @field_validator(
        "device_class",
        "manufacturer",
        "model",
        "profile_id",
        "node_id",
        "bus_id",
        "stable_transport_identifier",
        "ip_address",
        "target_equipment_key",
    )
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None


class CommissioningSessionResponse(BaseModel):
    id: str
    lifecycle: CommissioningLifecycle
    device_class: str
    manufacturer: str
    model: str
    profile_id: str | None
    profile_version: str | None
    transport_kind: str | None
    node_id: str | None
    bus_id: str | None
    stable_transport_identifier: str | None
    unit_id: int | None
    ip_address: str | None
    target_equipment_key: str | None
    blocked_reason: str | None
    unsupported_reason: str | None
    version: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None


class CommissioningSessionListResponse(BaseModel):
    items: list[CommissioningSessionResponse]

CommissioningPreflightState = Literal["running", "completed"]
CommissioningPreflightResult = Literal["passed", "failed"]
CommissioningEvidenceLevel = Literal[
    "hardware_verified",
    "partially_verified",
    "unsupported",
    "unverified",
]


class CommissioningPreflightAttemptResponse(BaseModel):
    id: str
    session_id: str
    session_version: int
    state: CommissioningPreflightState
    result: CommissioningPreflightResult | None
    code: str | None
    evidence_level: CommissioningEvidenceLevel | None
    evidence: dict[str, object] | None
    actor_subject: str
    started_at: datetime
    completed_at: datetime | None


CommissioningActivationState = Literal[
    "pending_activation",
    "active",
    "activation_failed",
    "rolled_back",
    "recovery_required",
]


class CommissioningActivationPlanResponse(BaseModel):
    schema_version: int
    session_id: str
    session_version: int
    preflight_attempt_id: str
    preflight_completed_at: datetime
    preflight_evidence_level: CommissioningEvidenceLevel
    device_class: str
    manufacturer: str
    model: str
    profile_id: str
    profile_version: str
    device_family: str
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    target_equipment_key: str
    telemetry_source: str
    telemetry_equipment_id: str
    polling_mode: Literal["read_only_fc03"]
    binding_kind: Literal["refrigeration_controller", "commissioning_target"]
    warnings: list[str]
    will_not_perform: list[str]


class CommissioningActivationAttemptResponse(BaseModel):
    id: str
    session_id: str
    preflight_attempt_id: str
    session_version: int
    state: CommissioningActivationState
    plan: CommissioningActivationPlanResponse
    evidence: dict[str, object] | None
    actor_subject: str
    started_at: datetime
    completed_at: datetime | None
