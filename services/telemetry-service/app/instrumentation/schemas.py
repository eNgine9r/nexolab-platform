from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
)


RegistryLifecycleState = Literal["active", "inactive", "retired"]
CalibrationState = Literal["valid", "due", "expired", "revoked", "unknown"]

_CANONICAL_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_UNIT_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.%/^-]*$")
_FUTURE_PROCESS_ROLES = frozenset(
    {
        "suction_pressure",
        "condensing_pressure",
        "suction_line_temperature",
        "liquid_line_temperature",
        "atmospheric_pressure",
    }
)


class InstrumentWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_key: Annotated[str, Field(min_length=1, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    instrument_kind: Annotated[str, Field(min_length=1, max_length=64)]
    manufacturer: Annotated[str | None, Field(max_length=128)] = None
    model: Annotated[str | None, Field(max_length=128)] = None
    serial_number: Annotated[str | None, Field(max_length=128)] = None
    lifecycle_state: RegistryLifecycleState = "active"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("inventory_key")
    @classmethod
    def normalize_inventory_key(cls, value: str) -> str:
        return _required_text(value, "inventory_key")

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        return _required_text(value, "display_name")

    @field_validator("instrument_kind")
    @classmethod
    def validate_instrument_kind(cls, value: str) -> str:
        return _canonical_identifier(value, "instrument_kind")

    @field_validator("manufacturer", "model", "serial_number")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)


class InstrumentCreate(InstrumentWrite):
    pass


class InstrumentUpdate(InstrumentWrite):
    """Complete replacement of editable Instrument registry metadata."""


class InstrumentResponse(BaseModel):
    id: str
    inventory_key: str
    display_name: str
    instrument_kind: str
    manufacturer: str | None
    model: str | None
    serial_number: str | None
    lifecycle_state: RegistryLifecycleState
    metadata: dict[str, JsonValue]
    version: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class InstrumentListResponse(BaseModel):
    items: list[InstrumentResponse]


class SignalWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_key: Annotated[str, Field(min_length=1, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=255)]
    physical_quantity: Annotated[str, Field(min_length=1, max_length=64)]
    engineering_unit: Annotated[str, Field(min_length=1, max_length=64)]
    lifecycle_state: RegistryLifecycleState = "active"
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("business_key", "display_name")
    @classmethod
    def normalize_required_text(cls, value: str, info: object) -> str:
        field_name = getattr(info, "field_name", "value")
        return _required_text(value, field_name)

    @field_validator("physical_quantity")
    @classmethod
    def validate_physical_quantity(cls, value: str) -> str:
        normalized = _canonical_identifier(value, "physical_quantity")
        if normalized in _FUTURE_PROCESS_ROLES:
            raise ValueError(
                "physical_quantity must describe a process-neutral physical quantity, "
                "not a refrigeration process role"
            )
        return normalized

    @field_validator("engineering_unit")
    @classmethod
    def validate_engineering_unit(cls, value: str) -> str:
        normalized = value.strip()
        if not _UNIT_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("engineering_unit must be a canonical unit identifier")
        return normalized


class SignalCreate(SignalWrite):
    pass


class SignalUpdate(SignalWrite):
    """Complete replacement of editable Signal registry metadata."""


class SignalResponse(BaseModel):
    id: str
    instrument_id: str
    business_key: str
    display_name: str
    physical_quantity: str
    engineering_unit: str
    lifecycle_state: RegistryLifecycleState
    metadata: dict[str, JsonValue]
    version: int
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class SignalListResponse(BaseModel):
    items: list[SignalResponse]


class AcceptanceAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_for_calculation: bool
    effective_from: datetime
    state_label: Annotated[str | None, Field(max_length=64)] = None

    @field_validator("effective_from")
    @classmethod
    def validate_effective_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_from")

    @field_validator("state_label")
    @classmethod
    def normalize_state_label(cls, value: str | None) -> str | None:
        return _optional_text(value)


class AcceptanceRecordResponse(BaseModel):
    id: str
    instrument_id: str
    schema_version: Literal["acceptance-state/v1"]
    accepted_for_calculation: bool
    state_label: str | None
    effective_from: datetime
    effective_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class AcceptanceHistoryResponse(BaseModel):
    items: list[AcceptanceRecordResponse]


class CalibrationAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calibration_scope: Annotated[str, Field(min_length=1, max_length=64)] = (
        "instrument"
    )
    state: CalibrationState
    valid_from: datetime
    certificate_reference: Annotated[str | None, Field(max_length=512)] = None

    @field_validator("calibration_scope")
    @classmethod
    def validate_calibration_scope(cls, value: str) -> str:
        return _canonical_identifier(value, "calibration_scope")

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")

    @field_validator("certificate_reference")
    @classmethod
    def normalize_certificate_reference(cls, value: str | None) -> str | None:
        return _optional_text(value)


class CalibrationRecordResponse(BaseModel):
    id: str
    instrument_id: str
    calibration_scope: str
    schema_version: Literal["calibration-state/v1"]
    state: CalibrationState
    valid_from: datetime
    valid_to: datetime | None
    revision: int
    certificate_reference: str | None
    recorded_by: str
    recorded_at: datetime


class CalibrationHistoryResponse(BaseModel):
    items: list[CalibrationRecordResponse]


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    expected_version: int | None = None
    actual_version: int | None = None


class ApiErrorResponse(BaseModel):
    detail: ApiErrorDetail


def _required_text(value: str, field_name: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _canonical_identifier(value: str, field_name: str) -> str:
    normalized = value.strip().lower()
    if not _CANONICAL_IDENTIFIER_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must be a lowercase canonical identifier beginning with a letter"
        )
    return normalized


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone offset")
    return value.astimezone(UTC)
