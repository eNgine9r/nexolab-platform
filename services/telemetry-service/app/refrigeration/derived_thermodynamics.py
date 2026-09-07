from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, Sequence

from app.refrigeration.property_provider import (
    PropertyProviderError,
    SaturationPhase,
    SaturationTemperatureResult,
)

MetricId = Literal[
    "refrigeration.temperature.evaporation_saturation",
    "refrigeration.temperature.condensation_saturation",
    "refrigeration.superheat",
    "refrigeration.subcooling",
]
Availability = Literal["available", "unavailable"]
ReasonCode = Literal[
    "missing_required_source",
    "ambiguous_required_source",
    "invalid_timestamp",
    "invalid_context_provenance",
    "invalid_source_provenance",
    "circuit_not_active",
    "lifecycle_interval_mismatch",
    "configuration_interval_mismatch",
    "binding_interval_mismatch",
    "calculation_policy_mismatch",
    "invalid_source_value",
    "invalid_source_unit",
    "telemetry_quality_rejected",
    "sample_too_old",
    "future_sample_not_allowed",
    "future_sample_skew_exceeded",
    "cross_input_skew_exceeded",
    "instrument_acceptance_unavailable",
    "instrument_not_accepted",
    "acquisition_profile_unresolved",
    "acquisition_acceptance_unavailable",
    "acquisition_not_accepted",
    "calibration_unavailable",
    "calibration_state_rejected",
    "unknown_pressure_reference",
    "missing_atmospheric_pressure",
    "invalid_absolute_pressure",
    "provider_profile_mismatch",
    "provider_invalid_pressure",
    "provider_unsupported_refrigerant",
    "provider_unsupported_phase",
    "provider_unsupported_provider_profile",
    "provider_version_mismatch",
    "provider_domain_error",
    "provider_error",
    "provider_non_finite_result",
]

ACCEPTANCE_SCHEMA_VERSION = "acceptance-state/v1"
CALIBRATION_SCHEMA_VERSION = "calibration-state/v1"
_ACCEPTED_TELEMETRY_QUALITY = "valid"
_ACCEPTABLE_CALIBRATION_STATES = frozenset({"valid", "due"})
_KNOWN_SOURCE_ROLES = frozenset(
    {
        "suction_pressure",
        "condensing_pressure",
        "suction_line_temperature",
        "liquid_line_temperature",
        "atmospheric_pressure",
    }
)
_PRESSURE_FACTORS_TO_PA = {"Pa": 1.0, "kPa": 1_000.0, "bar": 100_000.0}


class RefrigerantPropertyProvider(Protocol):
    provider_id: str
    provider_version: str
    provider_revision: str
    provider_profile: str

    def saturation_temperature(
        self,
        refrigerant_code: str,
        absolute_pressure_pa: float,
        phase: SaturationPhase | str,
    ) -> SaturationTemperatureResult: ...


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    record_id: str
    revision: int
    schema_version: str
    accepted_for_calculation: bool
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class CalibrationEvidence:
    record_id: str
    revision: int
    schema_version: str
    state: str
    valid_from: datetime
    valid_to: datetime | None
    certificate_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSourceEvidence:
    role: str
    signal_id: str
    binding_id: str
    binding_revision: int
    binding_valid_from: datetime
    binding_valid_to: datetime | None
    event_id: str
    captured_at: datetime
    value: float | None
    unit: str
    quality: str
    instrument_id: str
    instrument_version: int
    pressure_reference: str | None
    acquisition_profile_id: str | None
    acquisition_profile_version: str | None
    instrument_acceptance_at_sample: AcceptanceEvidence | None
    instrument_acceptance_at_observation: AcceptanceEvidence | None
    acquisition_acceptance_at_sample: AcceptanceEvidence | None
    acquisition_acceptance_at_observation: AcceptanceEvidence | None
    calibration_scope: str | None = None
    calibration_at_sample: CalibrationEvidence | None = None
    calibration_at_observation: CalibrationEvidence | None = None


@dataclass(frozen=True, slots=True)
class CalculationContext:
    circuit_id: str
    lifecycle_record_id: str
    lifecycle_revision: int
    lifecycle_state: str
    lifecycle_valid_from: datetime
    lifecycle_valid_to: datetime | None
    configuration_record_id: str
    configuration_revision: int
    configuration_valid_from: datetime
    configuration_valid_to: datetime | None
    refrigerant_code: str
    calculation_policy_version: str
    property_provider_profile: str

    @property
    def calculation_enabled(self) -> bool:
        return self.lifecycle_state == "active"


@dataclass(frozen=True, slots=True)
class CalculationPolicy:
    version: str
    maximum_age: timedelta
    maximum_future_clock_skew: timedelta
    maximum_cross_input_skew: timedelta
    accepted_calibration_states: frozenset[str]
    require_calibration_at_observation: bool
    calibration_required_roles: frozenset[str]

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("calculation policy version is required")
        for field_name, value in (
            ("maximum_age", self.maximum_age),
            ("maximum_future_clock_skew", self.maximum_future_clock_skew),
            ("maximum_cross_input_skew", self.maximum_cross_input_skew),
        ):
            if value < timedelta(0):
                raise ValueError(f"{field_name} must be non-negative")
        if not self.accepted_calibration_states:
            raise ValueError("accepted_calibration_states must be non-empty")
        if not self.accepted_calibration_states <= _ACCEPTABLE_CALIBRATION_STATES:
            raise ValueError(
                "accepted_calibration_states may contain only valid or due"
            )
        if not self.calibration_required_roles <= _KNOWN_SOURCE_ROLES:
            raise ValueError("calibration_required_roles contains an unsupported role")


@dataclass(frozen=True, slots=True)
class PressureConversionProvenance:
    source_role: str
    source_value: float
    source_unit: str
    pressure_reference: str
    source_pressure_pa: float
    atmospheric_event_id: str | None
    atmospheric_pressure_pa: float | None
    absolute_pressure_pa: float


@dataclass(frozen=True, slots=True)
class ProviderProvenance:
    provider_id: str
    provider_version: str
    provider_revision: str
    provider_profile: str
    refrigerant_code: str
    phase: str
    absolute_pressure_pa: float


@dataclass(frozen=True, slots=True)
class DerivedResult:
    metric: MetricId
    value: float | None
    unit: str
    availability: Availability
    reason_codes: tuple[ReasonCode, ...]
    observation_at: datetime
    effective_at: datetime | None
    computed_at: datetime
    formula_id: str
    formula_version: str
    context: CalculationContext
    policy: CalculationPolicy
    sources: tuple[ResolvedSourceEvidence, ...]
    pressure_conversion: PressureConversionProvenance | None
    provider: ProviderProvenance | None


@dataclass(frozen=True, slots=True)
class _ValidatedInputs:
    sources: tuple[ResolvedSourceEvidence, ...]
    effective_at: datetime


class DerivedThermodynamicsKernel:
    FORMULA_VERSION = "refrigeration-derived/v1"

    _FORMULAS: dict[MetricId, tuple[str, str]] = {
        "refrigeration.temperature.evaporation_saturation": (
            "evaporation_saturation",
            "degC",
        ),
        "refrigeration.temperature.condensation_saturation": (
            "condensation_saturation",
            "degC",
        ),
        "refrigeration.superheat": ("superheat", "K"),
        "refrigeration.subcooling": ("subcooling", "K"),
    }

    def __init__(self, provider: RefrigerantPropertyProvider) -> None:
        self._provider = provider

    def calculate(
        self,
        metric: MetricId,
        *,
        context: CalculationContext,
        policy: CalculationPolicy,
        observation_at: datetime,
        computed_at: datetime,
        sources: Sequence[ResolvedSourceEvidence],
    ) -> DerivedResult:
        formula_id, unit = self._FORMULAS[metric]
        base_sources = tuple(sources)
        time_reason = self._validate_evaluation_time(observation_at, computed_at)
        if time_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                base_sources,
                time_reason,
                complete=False,
            )
        context_reason = self._validate_context(context, policy, observation_at)
        if context_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                base_sources,
                context_reason,
                complete=False,
            )

        required_roles = self._base_required_roles(metric)
        selected, source_reason = self._select_roles(base_sources, required_roles)
        if source_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                tuple(selected),
                source_reason,
                complete=False,
            )

        pressure_role = (
            "suction_pressure"
            if metric
            in {
                "refrigeration.temperature.evaporation_saturation",
                "refrigeration.superheat",
            }
            else "condensing_pressure"
        )
        pressure_source = next(
            source for source in selected if source.role == pressure_role
        )
        if pressure_source.pressure_reference == "gauge":
            atmospheric, atmosphere_reason = self._select_one(
                base_sources, "atmospheric_pressure"
            )
            if atmosphere_reason is not None:
                reason: ReasonCode = (
                    "missing_atmospheric_pressure"
                    if atmosphere_reason == "missing_required_source"
                    else atmosphere_reason
                )
                return self._unavailable(
                    metric,
                    unit,
                    formula_id,
                    context,
                    policy,
                    observation_at,
                    computed_at,
                    tuple(selected),
                    reason,
                    complete=False,
                )
            assert atmospheric is not None
            selected.append(atmospheric)

        validated, gate_reason = self._validate_sources(
            tuple(selected), context, policy, observation_at
        )
        if gate_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                tuple(selected),
                gate_reason,
                complete=True,
            )
        assert validated is not None

        absolute_pressure, conversion, pressure_reason = self._absolute_pressure(
            pressure_source, tuple(selected)
        )
        if pressure_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                validated.sources,
                pressure_reason,
                complete=True,
                effective_at=validated.effective_at,
            )
        assert absolute_pressure is not None and conversion is not None

        phase = (
            SaturationPhase.DEW_EVAPORATION
            if pressure_role == "suction_pressure"
            else SaturationPhase.BUBBLE_CONDENSATION
        )
        saturation, provider_reason = self._saturation(
            context, absolute_pressure, phase
        )
        if provider_reason is not None:
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                validated.sources,
                provider_reason,
                complete=True,
                effective_at=validated.effective_at,
                pressure_conversion=conversion,
            )
        assert saturation is not None
        provider_provenance = ProviderProvenance(
            provider_id=saturation.provider_id,
            provider_version=saturation.provider_version,
            provider_revision=saturation.provider_revision,
            provider_profile=saturation.provider_profile,
            refrigerant_code=saturation.refrigerant_code,
            phase=saturation.phase.value,
            absolute_pressure_pa=saturation.absolute_pressure_pa,
        )
        saturation_deg_c = saturation.temperature_k - 273.15

        value = saturation_deg_c
        if metric == "refrigeration.superheat":
            line_temperature = next(
                source
                for source in validated.sources
                if source.role == "suction_line_temperature"
            )
            value = float(line_temperature.value) - saturation_deg_c  # type: ignore[arg-type]
        elif metric == "refrigeration.subcooling":
            line_temperature = next(
                source
                for source in validated.sources
                if source.role == "liquid_line_temperature"
            )
            value = saturation_deg_c - float(line_temperature.value)  # type: ignore[arg-type]
        if not math.isfinite(value):
            return self._unavailable(
                metric,
                unit,
                formula_id,
                context,
                policy,
                observation_at,
                computed_at,
                validated.sources,
                "invalid_source_value",
                complete=True,
                effective_at=validated.effective_at,
                pressure_conversion=conversion,
                provider=provider_provenance,
            )

        return DerivedResult(
            metric=metric,
            value=value,
            unit=unit,
            availability="available",
            reason_codes=(),
            observation_at=observation_at,
            effective_at=validated.effective_at,
            computed_at=computed_at,
            formula_id=formula_id,
            formula_version=self.FORMULA_VERSION,
            context=context,
            policy=policy,
            sources=validated.sources,
            pressure_conversion=conversion,
            provider=provider_provenance,
        )

    @staticmethod
    def _base_required_roles(metric: MetricId) -> tuple[str, ...]:
        if metric == "refrigeration.temperature.evaporation_saturation":
            return ("suction_pressure",)
        if metric == "refrigeration.temperature.condensation_saturation":
            return ("condensing_pressure",)
        if metric == "refrigeration.superheat":
            return ("suction_pressure", "suction_line_temperature")
        return ("condensing_pressure", "liquid_line_temperature")

    @staticmethod
    def _select_roles(
        sources: tuple[ResolvedSourceEvidence, ...], roles: tuple[str, ...]
    ) -> tuple[list[ResolvedSourceEvidence], ReasonCode | None]:
        selected: list[ResolvedSourceEvidence] = []
        for role in roles:
            source, reason = DerivedThermodynamicsKernel._select_one(sources, role)
            if reason is not None:
                return selected, reason
            assert source is not None
            selected.append(source)
        return selected, None

    @staticmethod
    def _select_one(
        sources: Sequence[ResolvedSourceEvidence], role: str
    ) -> tuple[ResolvedSourceEvidence | None, ReasonCode | None]:
        matches = [source for source in sources if source.role == role]
        if not matches:
            return None, "missing_required_source"
        if len(matches) != 1:
            return None, "ambiguous_required_source"
        return matches[0], None

    @staticmethod
    def _validate_evaluation_time(
        observation_at: datetime, computed_at: datetime
    ) -> ReasonCode | None:
        if not _aware(observation_at) or not _aware(computed_at):
            return "invalid_timestamp"
        return None

    @staticmethod
    def _validate_context(
        context: CalculationContext, policy: CalculationPolicy, observation_at: datetime
    ) -> ReasonCode | None:
        if (
            not context.circuit_id.strip()
            or not context.lifecycle_record_id.strip()
            or context.lifecycle_revision < 1
            or not context.configuration_record_id.strip()
            or context.configuration_revision < 1
            or not context.refrigerant_code.strip()
            or not context.calculation_policy_version.strip()
            or not context.property_provider_profile.strip()
        ):
            return "invalid_context_provenance"
        if context.calculation_policy_version != policy.version:
            return "calculation_policy_mismatch"
        if not context.calculation_enabled:
            return "circuit_not_active"
        if not _contains(
            context.lifecycle_valid_from, context.lifecycle_valid_to, observation_at
        ):
            return "lifecycle_interval_mismatch"
        if not _contains(
            context.configuration_valid_from,
            context.configuration_valid_to,
            observation_at,
        ):
            return "configuration_interval_mismatch"
        return None

    def _validate_sources(
        self,
        sources: tuple[ResolvedSourceEvidence, ...],
        context: CalculationContext,
        policy: CalculationPolicy,
        observation_at: datetime,
    ) -> tuple[_ValidatedInputs | None, ReasonCode | None]:
        for source in sources:
            reason = self._validate_source(source, context, policy, observation_at)
            if reason is not None:
                return None, reason
        captured = [source.captured_at for source in sources]
        if max(captured) - min(captured) > policy.maximum_cross_input_skew:
            return None, "cross_input_skew_exceeded"
        effective_at = min(observation_at, min(captured))
        return _ValidatedInputs(sources=sources, effective_at=effective_at), None

    def _validate_source(
        self,
        source: ResolvedSourceEvidence,
        context: CalculationContext,
        policy: CalculationPolicy,
        observation_at: datetime,
    ) -> ReasonCode | None:
        if (
            source.role not in _KNOWN_SOURCE_ROLES
            or not source.signal_id.strip()
            or not source.binding_id.strip()
            or source.binding_revision < 1
            or not source.event_id.strip()
            or not source.instrument_id.strip()
            or source.instrument_version < 1
        ):
            return "invalid_source_provenance"
        if not _aware(source.captured_at):
            return "invalid_timestamp"
        if not _contains(
            source.binding_valid_from, source.binding_valid_to, observation_at
        ) or not _contains(
            source.binding_valid_from, source.binding_valid_to, source.captured_at
        ):
            return "binding_interval_mismatch"
        if not _contains(
            context.configuration_valid_from,
            context.configuration_valid_to,
            source.captured_at,
        ):
            return "configuration_interval_mismatch"
        if source.role in {
            "suction_pressure",
            "condensing_pressure",
            "atmospheric_pressure",
        }:
            if source.unit not in _PRESSURE_FACTORS_TO_PA:
                return "invalid_source_unit"
            if source.role == "atmospheric_pressure":
                if source.pressure_reference != "absolute":
                    return "unknown_pressure_reference"
            elif source.pressure_reference not in {"absolute", "gauge"}:
                return "unknown_pressure_reference"
        elif source.role in {"suction_line_temperature", "liquid_line_temperature"}:
            if source.unit != "degC":
                return "invalid_source_unit"

        if (
            not source.acquisition_profile_id
            or not source.acquisition_profile_id.strip()
        ):
            return "acquisition_profile_unresolved"
        if (
            not source.acquisition_profile_version
            or not source.acquisition_profile_version.strip()
        ):
            return "acquisition_profile_unresolved"

        if source.value is None:
            return "invalid_source_value"
        try:
            numeric = float(source.value)
        except (TypeError, ValueError, OverflowError):
            return "invalid_source_value"
        if not math.isfinite(numeric):
            return "invalid_source_value"
        if source.quality != _ACCEPTED_TELEMETRY_QUALITY:
            return "telemetry_quality_rejected"

        if source.captured_at <= observation_at:
            if observation_at - source.captured_at > policy.maximum_age:
                return "sample_too_old"
        else:
            future_offset = source.captured_at - observation_at
            if policy.maximum_future_clock_skew == timedelta(0):
                return "future_sample_not_allowed"
            if future_offset > policy.maximum_future_clock_skew:
                return "future_sample_skew_exceeded"

        for evidence, at, unavailable_reason, rejected_reason in (
            (
                source.instrument_acceptance_at_sample,
                source.captured_at,
                "instrument_acceptance_unavailable",
                "instrument_not_accepted",
            ),
            (
                source.instrument_acceptance_at_observation,
                observation_at,
                "instrument_acceptance_unavailable",
                "instrument_not_accepted",
            ),
            (
                source.acquisition_acceptance_at_sample,
                source.captured_at,
                "acquisition_acceptance_unavailable",
                "acquisition_not_accepted",
            ),
            (
                source.acquisition_acceptance_at_observation,
                observation_at,
                "acquisition_acceptance_unavailable",
                "acquisition_not_accepted",
            ),
        ):
            reason = _validate_acceptance(
                evidence, at, unavailable_reason, rejected_reason
            )
            if reason is not None:
                return reason

        if source.role in policy.calibration_required_roles:
            reason = _validate_calibration(
                source.calibration_at_sample, source.captured_at, policy
            )
            if reason is not None:
                return reason
            if policy.require_calibration_at_observation:
                reason = _validate_calibration(
                    source.calibration_at_observation, observation_at, policy
                )
                if reason is not None:
                    return reason
        return None

    @staticmethod
    def _absolute_pressure(
        pressure: ResolvedSourceEvidence, sources: tuple[ResolvedSourceEvidence, ...]
    ) -> tuple[float | None, PressureConversionProvenance | None, ReasonCode | None]:
        source_pa = _pressure_to_pa(pressure.value, pressure.unit)
        if source_pa is None:
            return (
                None,
                None,
                "invalid_source_unit"
                if pressure.unit not in _PRESSURE_FACTORS_TO_PA
                else "invalid_absolute_pressure",
            )
        reference = pressure.pressure_reference
        if reference == "absolute":
            absolute = source_pa
            atmospheric = None
        elif reference == "gauge":
            atmosphere, reason = DerivedThermodynamicsKernel._select_one(
                sources, "atmospheric_pressure"
            )
            if reason is not None or atmosphere is None:
                return None, None, "missing_atmospheric_pressure"
            if atmosphere.pressure_reference != "absolute":
                return None, None, "unknown_pressure_reference"
            atmospheric = _pressure_to_pa(atmosphere.value, atmosphere.unit)
            if atmospheric is None:
                return (
                    None,
                    None,
                    "invalid_source_unit"
                    if atmosphere.unit not in _PRESSURE_FACTORS_TO_PA
                    else "invalid_absolute_pressure",
                )
            if atmospheric <= 0.0:
                return None, None, "invalid_absolute_pressure"
            absolute = source_pa + atmospheric
        else:
            return None, None, "unknown_pressure_reference"
        if not math.isfinite(absolute) or absolute <= 0.0:
            return None, None, "invalid_absolute_pressure"
        return (
            absolute,
            PressureConversionProvenance(
                source_role=pressure.role,
                source_value=float(pressure.value),  # type: ignore[arg-type]
                source_unit=pressure.unit,
                pressure_reference=reference,
                source_pressure_pa=source_pa,
                atmospheric_event_id=(
                    atmosphere.event_id
                    if reference == "gauge" and atmosphere is not None
                    else None
                ),
                atmospheric_pressure_pa=atmospheric,
                absolute_pressure_pa=absolute,
            ),
            None,
        )

    def _saturation(
        self,
        context: CalculationContext,
        absolute_pressure_pa: float,
        phase: SaturationPhase,
    ) -> tuple[SaturationTemperatureResult | None, ReasonCode | None]:
        if context.property_provider_profile != self._provider.provider_profile:
            return None, "provider_profile_mismatch"
        try:
            result = self._provider.saturation_temperature(
                context.refrigerant_code, absolute_pressure_pa, phase
            )
        except PropertyProviderError as exc:
            return None, _provider_reason(exc)
        return result, None

    def _unavailable(
        self,
        metric: MetricId,
        unit: str,
        formula_id: str,
        context: CalculationContext,
        policy: CalculationPolicy,
        observation_at: datetime,
        computed_at: datetime,
        sources: tuple[ResolvedSourceEvidence, ...],
        reason: ReasonCode,
        *,
        complete: bool,
        effective_at: datetime | None = None,
        pressure_conversion: PressureConversionProvenance | None = None,
        provider: ProviderProvenance | None = None,
    ) -> DerivedResult:
        if (
            effective_at is None
            and complete
            and sources
            and all(_aware(source.captured_at) for source in sources)
        ):
            effective_at = min(
                observation_at, min(source.captured_at for source in sources)
            )
        return DerivedResult(
            metric=metric,
            value=None,
            unit=unit,
            availability="unavailable",
            reason_codes=(reason,),
            observation_at=observation_at,
            effective_at=effective_at if complete else None,
            computed_at=computed_at,
            formula_id=formula_id,
            formula_version=self.FORMULA_VERSION,
            context=context,
            policy=policy,
            sources=sources,
            pressure_conversion=pressure_conversion,
            provider=provider,
        )


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _contains(valid_from: datetime, valid_to: datetime | None, value: datetime) -> bool:
    if (
        not _aware(valid_from)
        or not _aware(value)
        or (valid_to is not None and not _aware(valid_to))
    ):
        return False
    return valid_from <= value and (valid_to is None or value < valid_to)


def _pressure_to_pa(value: float | None, unit: str) -> float | None:
    factor = _PRESSURE_FACTORS_TO_PA.get(unit)
    if factor is None or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    pressure = numeric * factor
    if not math.isfinite(pressure):
        return None
    return pressure


def _validate_acceptance(
    evidence: AcceptanceEvidence | None,
    at: datetime,
    unavailable_reason: Literal[
        "instrument_acceptance_unavailable", "acquisition_acceptance_unavailable"
    ],
    rejected_reason: Literal["instrument_not_accepted", "acquisition_not_accepted"],
) -> ReasonCode | None:
    if (
        evidence is None
        or not evidence.record_id.strip()
        or evidence.revision < 1
        or evidence.schema_version != ACCEPTANCE_SCHEMA_VERSION
        or not _contains(evidence.valid_from, evidence.valid_to, at)
    ):
        return unavailable_reason
    if evidence.accepted_for_calculation is not True:
        return rejected_reason
    return None


def _validate_calibration(
    evidence: CalibrationEvidence | None, at: datetime, policy: CalculationPolicy
) -> ReasonCode | None:
    if (
        evidence is None
        or not evidence.record_id.strip()
        or evidence.revision < 1
        or evidence.schema_version != CALIBRATION_SCHEMA_VERSION
        or not _contains(evidence.valid_from, evidence.valid_to, at)
    ):
        return "calibration_unavailable"
    if evidence.state not in policy.accepted_calibration_states:
        return "calibration_state_rejected"
    return None


def _provider_reason(error: PropertyProviderError) -> ReasonCode:
    mapping: dict[str, ReasonCode] = {
        "invalid_pressure": "provider_invalid_pressure",
        "unsupported_refrigerant": "provider_unsupported_refrigerant",
        "unsupported_phase": "provider_unsupported_phase",
        "unsupported_provider_profile": "provider_unsupported_provider_profile",
        "provider_version_mismatch": "provider_version_mismatch",
        "provider_domain_error": "provider_domain_error",
        "provider_error": "provider_error",
        "non_finite_result": "provider_non_finite_result",
    }
    return mapping[error.reason]
