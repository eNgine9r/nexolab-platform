from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.refrigeration.circuit_models import CIRCUIT_PROCESS_ROLES


CircuitLifecycleState = Literal["active", "inactive", "retired"]
CircuitProcessRole = Literal[
    "suction_pressure",
    "condensing_pressure",
    "suction_line_temperature",
    "liquid_line_temperature",
    "atmospheric_pressure",
    "relative_humidity",
]
_REFRIGERANT_RE = re.compile(r"^[A-Z0-9][A-Z0-9._+-]*$")


def _text(value: str, field_name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone information")
    return value.astimezone(UTC)


class CircuitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equipment_id: Annotated[str, Field(min_length=1, max_length=36)]
    business_key: Annotated[str, Field(min_length=1, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    initial_state: CircuitLifecycleState = "active"
    valid_from: datetime

    @field_validator("equipment_id", "business_key", "display_name")
    @classmethod
    def normalize_text(cls, value: str, info: object) -> str:
        return _text(value, getattr(info, "field_name", "value"))

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")


class CircuitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    equipment_id: str
    business_key: str
    display_name: str
    created_by: str
    created_at: datetime


class CircuitListResponse(BaseModel):
    items: list[CircuitResponse]


class CircuitLifecycleAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: CircuitLifecycleState
    valid_from: datetime

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")


class CircuitLifecycleResponse(BaseModel):
    id: str
    circuit_id: str
    state: CircuitLifecycleState
    calculation_enabled: bool
    valid_from: datetime
    valid_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class CircuitLifecycleHistoryResponse(BaseModel):
    items: list[CircuitLifecycleResponse]


class CircuitConfigurationAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["refrigeration-circuit-configuration/v1"] = (
        "refrigeration-circuit-configuration/v1"
    )
    refrigerant_code: Annotated[str, Field(min_length=1, max_length=64)]
    calculation_policy_version: Annotated[str, Field(min_length=1, max_length=128)]
    property_provider_profile: Annotated[str | None, Field(max_length=255)] = None
    valid_from: datetime

    @field_validator("refrigerant_code")
    @classmethod
    def validate_refrigerant_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not _REFRIGERANT_RE.fullmatch(normalized):
            raise ValueError("refrigerant_code must be an explicit canonical identifier")
        return normalized

    @field_validator("calculation_policy_version")
    @classmethod
    def validate_calculation_policy(cls, value: str) -> str:
        return _text(value, "calculation_policy_version")

    @field_validator("property_provider_profile")
    @classmethod
    def normalize_provider_profile(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")


class CircuitConfigurationResponse(BaseModel):
    id: str
    circuit_id: str
    schema_version: Literal["refrigeration-circuit-configuration/v1"]
    refrigerant_code: str
    calculation_policy_version: str
    property_provider_profile: str | None
    valid_from: datetime
    valid_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class CircuitConfigurationHistoryResponse(BaseModel):
    items: list[CircuitConfigurationResponse]


class CircuitBindingAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: CircuitProcessRole
    signal_id: Annotated[str, Field(min_length=1, max_length=36)]
    valid_from: datetime

    @field_validator("signal_id")
    @classmethod
    def normalize_signal_id(cls, value: str) -> str:
        return _text(value, "signal_id")

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")


class CircuitBindingEndRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_to: datetime

    @field_validator("valid_to")
    @classmethod
    def validate_valid_to(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_to")


class CircuitBindingResponse(BaseModel):
    id: str
    circuit_id: str
    signal_id: str
    role: CircuitProcessRole
    physical_quantity: str
    engineering_unit: str
    instrument_kind: str
    pressure_reference: Literal["absolute", "gauge"] | None
    valid_from: datetime
    valid_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime
    ended_by: str | None
    ended_at: datetime | None


class CircuitBindingListResponse(BaseModel):
    items: list[CircuitBindingResponse]


assert set(CIRCUIT_PROCESS_ROLES) == {
    "suction_pressure",
    "condensing_pressure",
    "suction_line_temperature",
    "liquid_line_temperature",
    "atmospheric_pressure",
    "relative_humidity",
}
