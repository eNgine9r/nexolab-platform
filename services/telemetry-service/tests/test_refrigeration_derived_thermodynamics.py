from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from app.refrigeration.derived_thermodynamics import (
    ACCEPTANCE_SCHEMA_VERSION,
    CALIBRATION_SCHEMA_VERSION,
    AcceptanceEvidence,
    CalculationContext,
    CalculationPolicy,
    CalibrationEvidence,
    DerivedThermodynamicsKernel,
    ResolvedSourceEvidence,
)
from app.refrigeration.property_provider import (
    CANONICAL_PROPERTY_PROVIDER_PROFILE,
    CoolPropRefrigerantPropertyProvider,
    SaturationPhase,
    SaturationTemperatureResult,
)

OBS = datetime(2026, 9, 7, 10, 0, tzinfo=UTC)
COMPUTED = OBS + timedelta(seconds=1)
START = OBS - timedelta(hours=1)
END = OBS + timedelta(hours=1)


class StaticProvider:
    provider_id = "static"
    provider_version = "1"
    provider_revision = "test"
    provider_profile = "static/1"

    def saturation_temperature(
        self,
        refrigerant_code: str,
        absolute_pressure_pa: float,
        phase: SaturationPhase | str,
    ) -> SaturationTemperatureResult:
        resolved = SaturationPhase(phase)
        temperature_k = 273.15 + (
            5.0 if resolved is SaturationPhase.DEW_EVAPORATION else 40.0
        )
        return SaturationTemperatureResult(
            refrigerant_code=refrigerant_code,
            absolute_pressure_pa=absolute_pressure_pa,
            phase=resolved,
            temperature_k=temperature_k,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_revision=self.provider_revision,
            provider_profile=self.provider_profile,
        )


def _acceptance(
    *,
    accepted: bool = True,
    at_from: datetime = START,
    at_to: datetime | None = END,
    record_id: str = "acceptance-1",
) -> AcceptanceEvidence:
    return AcceptanceEvidence(
        record_id=record_id,
        revision=1,
        schema_version=ACCEPTANCE_SCHEMA_VERSION,
        accepted_for_calculation=accepted,
        valid_from=at_from,
        valid_to=at_to,
    )


def _calibration(
    *,
    state: str = "valid",
    at_from: datetime = START,
    at_to: datetime | None = END,
    record_id: str = "calibration-1",
) -> CalibrationEvidence:
    return CalibrationEvidence(
        record_id=record_id,
        revision=1,
        schema_version=CALIBRATION_SCHEMA_VERSION,
        state=state,
        valid_from=at_from,
        valid_to=at_to,
        certificate_reference="cert://fixture",
    )


def _source(
    role: str,
    *,
    value: float,
    unit: str,
    captured_at: datetime = OBS - timedelta(seconds=1),
    quality: str = "valid",
    pressure_reference: str | None = None,
) -> ResolvedSourceEvidence:
    accepted = _acceptance(record_id=f"acceptance-{role}")
    calibration = _calibration(record_id=f"calibration-{role}")
    return ResolvedSourceEvidence(
        role=role,
        signal_id=f"signal-{role}",
        binding_id=f"binding-{role}",
        binding_revision=1,
        binding_valid_from=START,
        binding_valid_to=END,
        event_id=f"event-{role}-{captured_at.isoformat()}",
        captured_at=captured_at,
        value=value,
        unit=unit,
        quality=quality,
        instrument_id=f"instrument-{role}",
        instrument_version=1,
        pressure_reference=pressure_reference,
        acquisition_profile_id=f"profile-{role}",
        acquisition_profile_version="1",
        instrument_acceptance_at_sample=accepted,
        instrument_acceptance_at_observation=accepted,
        acquisition_acceptance_at_sample=accepted,
        acquisition_acceptance_at_observation=accepted,
        calibration_scope="instrument",
        calibration_at_sample=calibration,
        calibration_at_observation=calibration,
    )


def _context(
    *,
    refrigerant: str = "R290",
    provider_profile: str = "static/1",
    lifecycle_state: str = "active",
) -> CalculationContext:
    return CalculationContext(
        circuit_id="circuit-1",
        lifecycle_record_id="life-1",
        lifecycle_revision=1,
        lifecycle_state=lifecycle_state,
        lifecycle_valid_from=START,
        lifecycle_valid_to=END,
        configuration_record_id="config-1",
        configuration_revision=1,
        configuration_valid_from=START,
        configuration_valid_to=END,
        refrigerant_code=refrigerant,
        calculation_policy_version="policy/v1",
        property_provider_profile=provider_profile,
    )


def _policy(
    *,
    maximum_age: timedelta = timedelta(seconds=30),
    future_skew: timedelta = timedelta(seconds=2),
    cross_skew: timedelta = timedelta(seconds=5),
    accepted_states: frozenset[str] = frozenset({"valid"}),
    require_calibration_at_observation: bool = True,
    calibration_roles: frozenset[str] = frozenset(
        {
            "suction_pressure",
            "condensing_pressure",
            "suction_line_temperature",
            "liquid_line_temperature",
            "atmospheric_pressure",
        }
    ),
) -> CalculationPolicy:
    return CalculationPolicy(
        version="policy/v1",
        maximum_age=maximum_age,
        maximum_future_clock_skew=future_skew,
        maximum_cross_input_skew=cross_skew,
        accepted_calibration_states=accepted_states,
        require_calibration_at_observation=require_calibration_at_observation,
        calibration_required_roles=calibration_roles,
    )


def _kernel() -> DerivedThermodynamicsKernel:
    return DerivedThermodynamicsKernel(StaticProvider())


def test_absolute_pressure_evaporation_and_provider_provenance() -> None:
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            )
        ],
    )
    assert result.availability == "available"
    assert result.value == pytest.approx(5.0)
    assert result.unit == "degC"
    assert result.effective_at == OBS - timedelta(seconds=1)
    assert result.pressure_conversion is not None
    assert result.pressure_conversion.absolute_pressure_pa == pytest.approx(400_000.0)
    assert result.pressure_conversion.atmospheric_event_id is None
    assert result.provider is not None
    assert result.provider.phase == "dew_evaporation"
    assert result.provider.provider_profile == "static/1"


def test_gauge_pressure_requires_and_records_real_atmosphere() -> None:
    suction = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="gauge"
    )
    atmosphere = _source(
        "atmospheric_pressure", value=101.325, unit="kPa", pressure_reference="absolute"
    )
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[suction, atmosphere],
    )
    assert result.availability == "available"
    assert result.pressure_conversion is not None
    assert result.pressure_conversion.source_pressure_pa == pytest.approx(400_000.0)
    assert result.pressure_conversion.atmospheric_pressure_pa == pytest.approx(
        101_325.0
    )
    assert result.pressure_conversion.absolute_pressure_pa == pytest.approx(501_325.0)
    assert result.pressure_conversion.atmospheric_event_id == atmosphere.event_id


def test_gauge_pressure_never_uses_standard_atmosphere_fallback() -> None:
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="gauge"
            )
        ],
    )
    assert result.availability == "unavailable"
    assert result.value is None
    assert result.reason_codes == ("missing_atmospheric_pressure",)
    assert result.effective_at is None


def test_superheat_and_subcooling_formulas_use_kelvin_difference_unit() -> None:
    superheat = _kernel().calculate(
        "refrigeration.superheat",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            ),
            _source("suction_line_temperature", value=12.5, unit="degC"),
        ],
    )
    subcooling = _kernel().calculate(
        "refrigeration.subcooling",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "condensing_pressure",
                value=12.0,
                unit="bar",
                pressure_reference="absolute",
            ),
            _source("liquid_line_temperature", value=33.0, unit="degC"),
        ],
    )
    assert superheat.availability == subcooling.availability == "available"
    assert superheat.value == pytest.approx(7.5)
    assert subcooling.value == pytest.approx(7.0)
    assert superheat.unit == subcooling.unit == "K"


@pytest.mark.parametrize("unit", ["C", "degF", "", "Kelvin"])
def test_temperature_unit_is_fail_closed(unit: str) -> None:
    result = _kernel().calculate(
        "refrigeration.superheat",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            ),
            _source("suction_line_temperature", value=12.0, unit=unit),
        ],
    )
    assert result.availability == "unavailable"
    assert result.reason_codes == ("invalid_source_unit",)


@pytest.mark.parametrize("unit", ["psi", "MPa", "barg", ""])
def test_pressure_unit_is_fail_closed(unit: str) -> None:
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit=unit, pressure_reference="absolute"
            )
        ],
    )
    assert result.availability == "unavailable"
    assert result.reason_codes == ("invalid_source_unit",)


@pytest.mark.parametrize("quality", ["sensor_error", "communication_error", "unknown"])
def test_non_valid_telemetry_quality_is_unavailable(quality: str) -> None:
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure",
                value=4.0,
                unit="bar",
                pressure_reference="absolute",
                quality=quality,
            )
        ],
    )
    assert result.reason_codes == ("telemetry_quality_rejected",)
    assert result.effective_at == OBS - timedelta(seconds=1)


def test_missing_or_ambiguous_source_fails_closed() -> None:
    missing = _kernel().calculate(
        "refrigeration.superheat",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            )
        ],
    )
    duplicate = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            ),
            replace(
                _source(
                    "suction_pressure",
                    value=4.1,
                    unit="bar",
                    pressure_reference="absolute",
                ),
                event_id="event-duplicate",
            ),
        ],
    )
    assert missing.reason_codes == ("missing_required_source",)
    assert duplicate.reason_codes == ("ambiguous_required_source",)
    assert missing.effective_at is None
    assert duplicate.effective_at is None


def test_maximum_age_boundary_is_inclusive_and_one_microsecond_over_fails() -> None:
    at_limit = _source(
        "suction_pressure",
        value=4.0,
        unit="bar",
        pressure_reference="absolute",
        captured_at=OBS - timedelta(seconds=30),
    )
    passed = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[at_limit],
    )
    failed = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            replace(
                at_limit,
                event_id="older",
                captured_at=OBS - timedelta(seconds=30, microseconds=1),
            )
        ],
    )
    assert passed.availability == "available"
    assert failed.reason_codes == ("sample_too_old",)


def test_future_skew_boundary_is_inclusive_and_effective_at_never_exceeds_observation() -> (
    None
):
    boundary = _source(
        "suction_pressure",
        value=4.0,
        unit="bar",
        pressure_reference="absolute",
        captured_at=OBS + timedelta(seconds=2),
    )
    passed = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[boundary],
    )
    failed = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            replace(
                boundary,
                event_id="too-future",
                captured_at=OBS + timedelta(seconds=2, microseconds=1),
            )
        ],
    )
    disallowed = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(future_skew=timedelta(0)),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[boundary],
    )
    assert passed.availability == "available"
    assert passed.effective_at == OBS
    assert failed.reason_codes == ("future_sample_skew_exceeded",)
    assert disallowed.reason_codes == ("future_sample_not_allowed",)


def test_cross_input_skew_boundary_is_inclusive() -> None:
    suction = _source(
        "suction_pressure",
        value=4.0,
        unit="bar",
        pressure_reference="absolute",
        captured_at=OBS - timedelta(seconds=5),
    )
    temp = _source("suction_line_temperature", value=12.0, unit="degC", captured_at=OBS)
    passed = _kernel().calculate(
        "refrigeration.superheat",
        context=_context(),
        policy=_policy(cross_skew=timedelta(seconds=5)),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[suction, temp],
    )
    failed = _kernel().calculate(
        "refrigeration.superheat",
        context=_context(),
        policy=_policy(cross_skew=timedelta(seconds=5) - timedelta(microseconds=1)),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[suction, temp],
    )
    assert passed.availability == "available"
    assert failed.reason_codes == ("cross_input_skew_exceeded",)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("instrument_acceptance_at_sample", "instrument_acceptance_unavailable"),
        ("instrument_acceptance_at_observation", "instrument_acceptance_unavailable"),
        ("acquisition_acceptance_at_sample", "acquisition_acceptance_unavailable"),
        ("acquisition_acceptance_at_observation", "acquisition_acceptance_unavailable"),
    ],
)
def test_missing_acceptance_authority_fails_closed(field: str, expected: str) -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[replace(source, **{field: None})],
    )
    assert result.reason_codes == (expected,)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("instrument_acceptance_at_sample", "instrument_not_accepted"),
        ("instrument_acceptance_at_observation", "instrument_not_accepted"),
        ("acquisition_acceptance_at_sample", "acquisition_not_accepted"),
        ("acquisition_acceptance_at_observation", "acquisition_not_accepted"),
    ],
)
def test_rejected_acceptance_authority_fails_closed(field: str, expected: str) -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            replace(
                source,
                **{field: _acceptance(accepted=False, record_id=f"rejected-{field}")},
            )
        ],
    )
    assert result.reason_codes == (expected,)


def test_unresolved_acquisition_profile_identity_fails_closed() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    for candidate in (
        replace(source, acquisition_profile_id=None),
        replace(source, acquisition_profile_version=None),
    ):
        result = _kernel().calculate(
            "refrigeration.temperature.evaporation_saturation",
            context=_context(),
            policy=_policy(),
            observation_at=OBS,
            computed_at=COMPUTED,
            sources=[candidate],
        )
        assert result.reason_codes == ("acquisition_profile_unresolved",)


def test_calibration_policy_is_explicit_and_due_can_be_authorized() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    due = _calibration(state="due", record_id="due")
    candidate = replace(
        source, calibration_at_sample=due, calibration_at_observation=due
    )
    rejected = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[candidate],
    )
    accepted = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(accepted_states=frozenset({"valid", "due"})),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[candidate],
    )
    assert rejected.reason_codes == ("calibration_state_rejected",)
    assert accepted.availability == "available"


def test_observation_time_calibration_gate_can_be_explicitly_disabled() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    candidate = replace(source, calibration_at_observation=None)
    accepted = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(require_calibration_at_observation=False),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[candidate],
    )
    rejected = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(require_calibration_at_observation=True),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[candidate],
    )
    assert accepted.availability == "available"
    assert rejected.reason_codes == ("calibration_unavailable",)


def test_inactive_circuit_and_policy_version_mismatch_fail_closed() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    inactive = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(lifecycle_state="inactive"),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[source],
    )
    mismatched_policy = replace(_policy(), version="policy/v2")
    mismatch = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=mismatched_policy,
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[source],
    )
    assert inactive.reason_codes == ("circuit_not_active",)
    assert mismatch.reason_codes == ("calculation_policy_mismatch",)


def test_provider_profile_mismatch_fails_before_property_call() -> None:
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(provider_profile="other/1"),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
            )
        ],
    )
    assert result.reason_codes == ("provider_profile_mismatch",)
    assert result.provider is None


def test_real_pinned_coolprop_r290_and_r407c_phase_semantics() -> None:
    provider = CoolPropRefrigerantPropertyProvider()
    kernel = DerivedThermodynamicsKernel(provider)
    context_r290 = _context(
        refrigerant="R290", provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE
    )
    evap = kernel.calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=context_r290,
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure",
                value=500.0,
                unit="kPa",
                pressure_reference="absolute",
            )
        ],
    )
    assert evap.availability == "available"
    assert evap.provider is not None and evap.provider.phase == "dew_evaporation"

    context_r407c = _context(
        refrigerant="R407C", provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE
    )
    dew = kernel.calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=context_r407c,
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure",
                value=10.0,
                unit="bar",
                pressure_reference="absolute",
            )
        ],
    )
    bubble = kernel.calculate(
        "refrigeration.temperature.condensation_saturation",
        context=context_r407c,
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "condensing_pressure",
                value=10.0,
                unit="bar",
                pressure_reference="absolute",
            )
        ],
    )
    assert dew.availability == bubble.availability == "available"
    assert dew.value is not None and bubble.value is not None
    assert dew.value - bubble.value > 5.0
    assert dew.provider is not None and dew.provider.phase == "dew_evaporation"
    assert (
        bubble.provider is not None and bubble.provider.phase == "bubble_condensation"
    )


def test_real_provider_unsupported_refrigerant_and_domain_failure_are_typed_unavailable() -> (
    None
):
    provider = CoolPropRefrigerantPropertyProvider()
    kernel = DerivedThermodynamicsKernel(provider)
    unsupported = kernel.calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(
            refrigerant="R449A", provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE
        ),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure", value=5.0, unit="bar", pressure_reference="absolute"
            )
        ],
    )
    domain = kernel.calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[
            _source(
                "suction_pressure",
                value=1_000_000_000.0,
                unit="Pa",
                pressure_reference="absolute",
            )
        ],
    )
    assert unsupported.reason_codes == ("provider_unsupported_refrigerant",)
    assert domain.reason_codes == ("provider_domain_error",)
    assert unsupported.value is domain.value is None


def test_policy_rejects_hidden_or_unsafe_defaults() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _policy(maximum_age=timedelta(seconds=-1))
    with pytest.raises(ValueError, match="non-empty"):
        _policy(accepted_states=frozenset())
    with pytest.raises(ValueError, match="valid or due"):
        _policy(accepted_states=frozenset({"expired"}))
    with pytest.raises(ValueError, match="unsupported role"):
        _policy(calibration_roles=frozenset({"not-a-role"}))


def test_incomplete_source_provenance_fails_closed() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    for candidate in (
        replace(source, event_id=""),
        replace(source, signal_id=""),
        replace(source, binding_id=""),
        replace(source, binding_revision=0),
        replace(source, instrument_id=""),
        replace(source, instrument_version=0),
    ):
        result = _kernel().calculate(
            "refrigeration.temperature.evaporation_saturation",
            context=_context(),
            policy=_policy(),
            observation_at=OBS,
            computed_at=COMPUTED,
            sources=[candidate],
        )
        assert result.reason_codes == ("invalid_source_provenance",)


def test_incomplete_context_provenance_fails_closed() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    for context in (
        replace(_context(), circuit_id=""),
        replace(_context(), lifecycle_record_id=""),
        replace(_context(), lifecycle_revision=0),
        replace(_context(), configuration_record_id=""),
        replace(_context(), configuration_revision=0),
    ):
        result = _kernel().calculate(
            "refrigeration.temperature.evaporation_saturation",
            context=context,
            policy=_policy(),
            observation_at=OBS,
            computed_at=COMPUTED,
            sources=[source],
        )
        assert result.reason_codes == ("invalid_context_provenance",)


def test_non_positive_absolute_atmospheric_source_fails_closed() -> None:
    suction = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="gauge"
    )
    atmosphere = _source(
        "atmospheric_pressure", value=-0.5, unit="bar", pressure_reference="absolute"
    )
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[suction, atmosphere],
    )
    assert result.availability == "unavailable"
    assert result.reason_codes == ("invalid_absolute_pressure",)


def test_result_is_reproducible_and_does_not_mutate_source_evidence() -> None:
    source = _source(
        "suction_pressure", value=4.0, unit="bar", pressure_reference="absolute"
    )
    before = source
    first = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[source],
    )
    second = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[source],
    )
    assert first == second
    assert source == before


def test_later_quality_rejection_keeps_source_provenance_and_effective_time() -> None:
    source = _source(
        "suction_pressure",
        value=4.0,
        unit="bar",
        pressure_reference="absolute",
        quality="unknown",
    )
    result = _kernel().calculate(
        "refrigeration.temperature.evaporation_saturation",
        context=_context(),
        policy=_policy(),
        observation_at=OBS,
        computed_at=COMPUTED,
        sources=[source],
    )
    assert result.availability == "unavailable"
    assert result.sources == (source,)
    assert result.effective_at == source.captured_at
    assert result.value is None
