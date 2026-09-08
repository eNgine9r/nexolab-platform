from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    field_validator,
    model_validator,
)


RegistryLifecycleState = Literal["active", "inactive", "retired"]
CalibrationState = Literal["valid", "due", "expired", "revoked", "unknown"]
PressureReference = Literal["absolute", "gauge"]

_CANONICAL_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_UNIT_IDENTIFIER_RE = re.compile(r"^(?:%RH|[A-Za-z][A-Za-z0-9_.%/^-]*)$")
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
    pressure_reference: PressureReference | None = None
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
    pressure_reference: PressureReference | None
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

    accepted_for_calculation: StrictBool
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


AnalogElectricalInputClass = Literal["current_loop_4_20ma"]
AnalogScalingPolicy = Literal["linear_two_point"]
AnalogRangePolicy = Literal["unavailable"]
AnalogEvidenceStatus = Literal[
    "software_verified", "hardware_unverified", "hardware_verified"
]
AnalogStorageDecimal = Annotated[Decimal, Field(max_digits=38, decimal_places=18)]


class AnalogScalingProfileAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["analog-scaling/v1"] = "analog-scaling/v1"
    electrical_input_class: AnalogElectricalInputClass = "current_loop_4_20ma"
    raw_unit: Annotated[str, Field(min_length=1, max_length=32)]
    raw_min: AnalogStorageDecimal
    raw_max: AnalogStorageDecimal
    engineering_min: AnalogStorageDecimal
    engineering_max: AnalogStorageDecimal
    engineering_unit: Annotated[str, Field(min_length=1, max_length=64)]
    scaling_policy: AnalogScalingPolicy = "linear_two_point"
    under_range_policy: AnalogRangePolicy = "unavailable"
    over_range_policy: AnalogRangePolicy = "unavailable"
    acquisition_device_family: Annotated[str | None, Field(max_length=64)] = None
    acquisition_profile_id: Annotated[str | None, Field(max_length=128)] = None
    acquisition_profile_version: Annotated[str | None, Field(max_length=128)] = None
    acquisition_channel_reference: Annotated[str | None, Field(max_length=255)] = None
    acquisition_source_id: Annotated[str | None, Field(max_length=36)] = None
    evidence_reference: Annotated[str | None, Field(max_length=512)] = None
    calibration_scope: Annotated[str, Field(min_length=1, max_length=64)] = "instrument"
    evidence_status: AnalogEvidenceStatus = "hardware_unverified"
    effective_from: datetime

    @field_validator("raw_unit", "engineering_unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        normalized = value.strip()
        if not _UNIT_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("unit must be a canonical unit identifier")
        return normalized

    @field_validator("calibration_scope")
    @classmethod
    def validate_calibration_scope(cls, value: str) -> str:
        return _canonical_identifier(value, "calibration_scope")

    @field_validator(
        "acquisition_device_family",
        "acquisition_profile_id",
        "acquisition_profile_version",
        "acquisition_channel_reference",
        "acquisition_source_id",
        "evidence_reference",
    )
    @classmethod
    def normalize_optional_provenance(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("effective_from")
    @classmethod
    def validate_effective_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "effective_from")

    @field_validator("raw_min", "raw_max", "engineering_min", "engineering_max")
    @classmethod
    def validate_finite_decimal(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("analog scaling values must be finite decimals")
        return value

    @model_validator(mode="after")
    def validate_profile(self) -> "AnalogScalingProfileAppendRequest":
        if self.raw_min >= self.raw_max:
            raise ValueError("raw_min must be strictly less than raw_max")
        if self.evidence_status == "hardware_verified":
            required = (
                self.acquisition_device_family,
                self.acquisition_profile_id,
                self.acquisition_profile_version,
                self.acquisition_channel_reference,
                self.evidence_reference,
            )
            if any(value is None for value in required):
                raise ValueError(
                    "hardware_verified analog profiles require complete acquisition provenance"
                )
        return self


class AnalogScalingProfileResponse(BaseModel):
    id: str
    signal_id: str
    schema_version: Literal["analog-scaling/v1"]
    electrical_input_class: AnalogElectricalInputClass
    raw_unit: str
    raw_min: Decimal
    raw_max: Decimal
    engineering_min: Decimal
    engineering_max: Decimal
    engineering_unit: str
    scaling_policy: AnalogScalingPolicy
    under_range_policy: AnalogRangePolicy
    over_range_policy: AnalogRangePolicy
    acquisition_device_family: str | None
    acquisition_profile_id: str | None
    acquisition_profile_version: str | None
    acquisition_channel_reference: str | None
    acquisition_source_id: str | None
    evidence_reference: str | None
    calibration_scope: str
    evidence_status: AnalogEvidenceStatus
    effective_from: datetime
    effective_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class AnalogScalingHistoryResponse(BaseModel):
    items: list[AnalogScalingProfileResponse]


class AnalogScalingEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_value: Decimal
    at: datetime

    @field_validator("raw_value")
    @classmethod
    def validate_raw_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("raw_value must be a finite decimal")
        return value

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "at")


class AnalogScalingEvaluationResponse(BaseModel):
    profile_id: str
    profile_revision: int
    evidence_status: AnalogEvidenceStatus
    raw_value: Decimal
    engineering_value: Decimal
    engineering_unit: str


AcquisitionEvidenceStatus = Literal[
    "software_verified", "hardware_unverified", "hardware_verified"
]


class AcquisitionSourceAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["acquisition-source/v1"] = "acquisition-source/v1"
    node_id: Annotated[str, Field(min_length=1, max_length=128)]
    equipment_id: Annotated[str, Field(min_length=1, max_length=128)]
    channel_id: Annotated[str, Field(min_length=1, max_length=128)]
    metric: Annotated[str, Field(min_length=1, max_length=128)]
    unit: Annotated[str, Field(min_length=1, max_length=64)]
    evidence_status: AcquisitionEvidenceStatus = "hardware_unverified"
    evidence_reference: Annotated[str | None, Field(max_length=512)] = None
    acquisition_profile_id: Annotated[str | None, Field(max_length=128)] = None
    acquisition_profile_version: Annotated[str | None, Field(max_length=128)] = None
    calibration_scope: Annotated[str | None, Field(max_length=64)] = None
    valid_from: datetime

    @field_validator("node_id", "equipment_id", "channel_id", "metric")
    @classmethod
    def normalize_source_identity(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(
                f"{getattr(info, 'field_name', 'source identity')} must not be blank"
            )
        return normalized

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str) -> str:
        normalized = value.strip()
        if not _UNIT_IDENTIFIER_RE.fullmatch(normalized):
            raise ValueError("unit must be a canonical unit identifier")
        return normalized

    @field_validator(
        "evidence_reference", "acquisition_profile_id", "acquisition_profile_version"
    )
    @classmethod
    def normalize_optional_source_provenance(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @field_validator("calibration_scope")
    @classmethod
    def normalize_calibration_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _canonical_identifier(value, "calibration_scope")

    @field_validator("valid_from")
    @classmethod
    def validate_valid_from(cls, value: datetime) -> datetime:
        return _aware_utc(value, "valid_from")

    @model_validator(mode="after")
    def validate_hardware_evidence(self) -> "AcquisitionSourceAppendRequest":
        if self.evidence_status == "hardware_verified" and not self.evidence_reference:
            raise ValueError(
                "hardware_verified acquisition sources require an evidence_reference"
            )
        profile_identity = (self.acquisition_profile_id, self.acquisition_profile_version)
        if (profile_identity[0] is None) != (profile_identity[1] is None):
            raise ValueError(
                "acquisition_profile_id and acquisition_profile_version must be provided together"
            )
        return self


class AcquisitionSourceResponse(BaseModel):
    id: str
    signal_id: str
    schema_version: Literal["acquisition-source/v1"]
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    unit: str
    evidence_status: AcquisitionEvidenceStatus
    evidence_reference: str | None
    acquisition_profile_id: str | None
    acquisition_profile_version: str | None
    calibration_scope: str | None
    valid_from: datetime
    valid_to: datetime | None
    revision: int
    recorded_by: str
    recorded_at: datetime


class AcquisitionSourceHistoryResponse(BaseModel):
    items: list[AcquisitionSourceResponse]


class HumidityObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_value: Decimal
    at: datetime

    @field_validator("raw_value")
    @classmethod
    def validate_raw_value(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("raw_value must be a finite decimal")
        return value

    @field_validator("at")
    @classmethod
    def validate_at(cls, value: datetime) -> datetime:
        return _aware_utc(value, "at")


class HumidityObservationResponse(BaseModel):
    signal_id: str
    physical_quantity: Literal["relative_humidity"]
    raw_value: Decimal
    value: Decimal
    unit: Literal["%RH"]
    source: AcquisitionSourceResponse
    profile_id: str
    profile_revision: int
    profile_evidence_status: AnalogEvidenceStatus
    evidence_status: AcquisitionEvidenceStatus


class PressureObservationRequest(AnalogScalingEvaluationRequest):
    pass


class PressureObservationResponse(BaseModel):
    signal_id: str
    physical_quantity: Literal["pressure"]
    pressure_reference: PressureReference
    raw_value: Decimal
    value: Decimal
    unit: str
    source: AcquisitionSourceResponse
    profile_id: str
    profile_revision: int
    profile_evidence_status: AnalogEvidenceStatus
    profile_evidence_reference: str | None
    evidence_status: AcquisitionEvidenceStatus


class AtmosphericPressureObservationRequest(AnalogScalingEvaluationRequest):
    pass


class AtmosphericPressureObservationResponse(BaseModel):
    signal_id: str
    physical_quantity: Literal["pressure"]
    pressure_reference: Literal["absolute"]
    raw_value: Decimal
    value: Decimal
    unit: str
    source: AcquisitionSourceResponse
    profile_id: str
    profile_revision: int
    profile_evidence_status: AnalogEvidenceStatus
    profile_evidence_reference: str | None
    evidence_status: AcquisitionEvidenceStatus


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
