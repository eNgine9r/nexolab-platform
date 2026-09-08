from __future__ import annotations

from datetime import datetime
from typing import Annotated, Callable

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime, BaseModel

from app.refrigeration.derived_read import (
    ALL_DERIVED_METRICS,
    DerivedReadItem,
    HistoricalDerivedReadService,
)
from app.refrigeration.derived_thermodynamics import MetricId
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


class AcceptanceEvidenceResponse(BaseModel):
    record_id: str
    revision: int
    schema_version: str
    accepted_for_calculation: bool
    valid_from: datetime
    valid_to: datetime | None


class CalibrationEvidenceResponse(BaseModel):
    record_id: str
    revision: int
    schema_version: str
    state: str
    valid_from: datetime
    valid_to: datetime | None
    certificate_reference: str | None


class SourceEvidenceResponse(BaseModel):
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
    acquisition_source_id: str | None
    acquisition_source_revision: int | None
    acquisition_source_valid_from: datetime | None
    acquisition_source_valid_to: datetime | None
    scaling_profile_id: str | None
    scaling_profile_revision: int | None
    scaling_profile_valid_from: datetime | None
    scaling_profile_valid_to: datetime | None
    calibration_scope: str | None
    instrument_acceptance_at_sample: AcceptanceEvidenceResponse | None
    instrument_acceptance_at_observation: AcceptanceEvidenceResponse | None
    acquisition_acceptance_at_sample: AcceptanceEvidenceResponse | None
    acquisition_acceptance_at_observation: AcceptanceEvidenceResponse | None
    calibration_at_sample: CalibrationEvidenceResponse | None
    calibration_at_observation: CalibrationEvidenceResponse | None


class CalculationContextResponse(BaseModel):
    circuit_id: str
    lifecycle_record_id: str
    lifecycle_revision: int
    lifecycle_state: str
    lifecycle_valid_from: datetime
    lifecycle_valid_to: datetime | None
    calculation_enabled: bool
    configuration_record_id: str
    configuration_revision: int
    configuration_valid_from: datetime
    configuration_valid_to: datetime | None
    refrigerant_code: str
    calculation_policy_version: str
    property_provider_profile: str


class CalculationPolicyEvidenceResponse(BaseModel):
    version: str
    maximum_age_ms: int
    maximum_future_clock_skew_ms: int
    maximum_cross_input_skew_ms: int
    accepted_calibration_states: list[str]
    require_calibration_at_observation: bool
    calibration_required_roles: list[str]


class PressureConversionResponse(BaseModel):
    source_role: str
    source_value: float
    source_unit: str
    pressure_reference: str
    source_pressure_pa: float
    atmospheric_event_id: str | None
    atmospheric_pressure_pa: float | None
    absolute_pressure_pa: float


class ProviderProvenanceResponse(BaseModel):
    provider_id: str
    provider_version: str
    provider_revision: str
    provider_profile: str
    refrigerant_code: str
    phase: str
    absolute_pressure_pa: float


class KernelDerivedResultResponse(BaseModel):
    metric: MetricId
    value: float | None
    unit: str
    availability: str
    reason_codes: list[str]
    observation_at: datetime
    effective_at: datetime | None
    computed_at: datetime
    formula_id: str
    formula_version: str
    context: CalculationContextResponse
    policy: CalculationPolicyEvidenceResponse
    sources: list[SourceEvidenceResponse]
    pressure_conversion: PressureConversionResponse | None
    provider: ProviderProvenanceResponse | None


class DerivedReadItemResponse(BaseModel):
    metric: MetricId
    availability: str
    reason_codes: list[str]
    observation_at: datetime
    computed_at: datetime
    kernel_result: KernelDerivedResultResponse | None


class DerivedReadResponse(BaseModel):
    circuit_id: str
    observation_at: datetime
    metrics: list[DerivedReadItemResponse]


def create_derived_read_router(
    service: HistoricalDerivedReadService,
    *,
    security_dependencies: SecurityDependencies | None = None,
    default_organization_id: str,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/refrigeration/circuits",
        tags=["refrigeration-derived"],
    )
    read_access = _access_dependency(
        security_dependencies, Permission.READ_DASHBOARD, default_organization_id
    )

    @router.get("/{circuit_id}/derived", response_model=DerivedReadResponse)
    def calculate_derived(
        circuit_id: str,
        observation_at: Annotated[AwareDatetime, Query()],
        metric: Annotated[list[MetricId] | None, Query()] = None,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> DerivedReadResponse:
        requested = metric if metric is not None else list(ALL_DERIVED_METRICS)
        items = service.calculate(
            circuit_id,
            observation_at,
            organization_id=authorized.principal.organization_id,
            metrics=requested,
        )
        return DerivedReadResponse(
            circuit_id=circuit_id,
            observation_at=observation_at,
            metrics=[_item_response(item) for item in items],
        )

    return router


def _item_response(item: DerivedReadItem) -> DerivedReadItemResponse:
    result = item.kernel_result
    kernel = None
    if result is not None:
        context = result.context
        policy = result.policy
        kernel = KernelDerivedResultResponse(
            metric=result.metric,
            value=result.value,
            unit=result.unit,
            availability=result.availability,
            reason_codes=list(result.reason_codes),
            observation_at=result.observation_at,
            effective_at=result.effective_at,
            computed_at=result.computed_at,
            formula_id=result.formula_id,
            formula_version=result.formula_version,
            context=CalculationContextResponse(
                circuit_id=context.circuit_id,
                lifecycle_record_id=context.lifecycle_record_id,
                lifecycle_revision=context.lifecycle_revision,
                lifecycle_state=context.lifecycle_state,
                lifecycle_valid_from=context.lifecycle_valid_from,
                lifecycle_valid_to=context.lifecycle_valid_to,
                calculation_enabled=context.calculation_enabled,
                configuration_record_id=context.configuration_record_id,
                configuration_revision=context.configuration_revision,
                configuration_valid_from=context.configuration_valid_from,
                configuration_valid_to=context.configuration_valid_to,
                refrigerant_code=context.refrigerant_code,
                calculation_policy_version=context.calculation_policy_version,
                property_provider_profile=context.property_provider_profile,
            ),
            policy=CalculationPolicyEvidenceResponse(
                version=policy.version,
                maximum_age_ms=int(policy.maximum_age.total_seconds() * 1000),
                maximum_future_clock_skew_ms=int(
                    policy.maximum_future_clock_skew.total_seconds() * 1000
                ),
                maximum_cross_input_skew_ms=int(
                    policy.maximum_cross_input_skew.total_seconds() * 1000
                ),
                accepted_calibration_states=sorted(policy.accepted_calibration_states),
                require_calibration_at_observation=(
                    policy.require_calibration_at_observation
                ),
                calibration_required_roles=sorted(policy.calibration_required_roles),
            ),
            sources=[_source_response(source) for source in result.sources],
            pressure_conversion=(
                PressureConversionResponse.model_validate(
                    result.pressure_conversion, from_attributes=True
                )
                if result.pressure_conversion is not None
                else None
            ),
            provider=(
                ProviderProvenanceResponse.model_validate(
                    result.provider, from_attributes=True
                )
                if result.provider is not None
                else None
            ),
        )
    return DerivedReadItemResponse(
        metric=item.metric,
        availability=item.availability,
        reason_codes=list(item.reason_codes),
        observation_at=item.observation_at,
        computed_at=item.computed_at,
        kernel_result=kernel,
    )


def _source_response(source) -> SourceEvidenceResponse:
    return SourceEvidenceResponse(
        role=source.role,
        signal_id=source.signal_id,
        binding_id=source.binding_id,
        binding_revision=source.binding_revision,
        binding_valid_from=source.binding_valid_from,
        binding_valid_to=source.binding_valid_to,
        event_id=source.event_id,
        captured_at=source.captured_at,
        value=source.value,
        unit=source.unit,
        quality=source.quality,
        instrument_id=source.instrument_id,
        instrument_version=source.instrument_version,
        pressure_reference=source.pressure_reference,
        acquisition_profile_id=source.acquisition_profile_id,
        acquisition_profile_version=source.acquisition_profile_version,
        acquisition_source_id=source.acquisition_source_id,
        acquisition_source_revision=source.acquisition_source_revision,
        acquisition_source_valid_from=source.acquisition_source_valid_from,
        acquisition_source_valid_to=source.acquisition_source_valid_to,
        scaling_profile_id=source.scaling_profile_id,
        scaling_profile_revision=source.scaling_profile_revision,
        scaling_profile_valid_from=source.scaling_profile_valid_from,
        scaling_profile_valid_to=source.scaling_profile_valid_to,
        calibration_scope=source.calibration_scope,
        instrument_acceptance_at_sample=_acceptance_response(
            source.instrument_acceptance_at_sample
        ),
        instrument_acceptance_at_observation=_acceptance_response(
            source.instrument_acceptance_at_observation
        ),
        acquisition_acceptance_at_sample=_acceptance_response(
            source.acquisition_acceptance_at_sample
        ),
        acquisition_acceptance_at_observation=_acceptance_response(
            source.acquisition_acceptance_at_observation
        ),
        calibration_at_sample=_calibration_response(source.calibration_at_sample),
        calibration_at_observation=_calibration_response(
            source.calibration_at_observation
        ),
    )


def _acceptance_response(value) -> AcceptanceEvidenceResponse | None:
    if value is None:
        return None
    return AcceptanceEvidenceResponse.model_validate(value, from_attributes=True)


def _calibration_response(value) -> CalibrationEvidenceResponse | None:
    if value is None:
        return None
    return CalibrationEvidenceResponse.model_validate(value, from_attributes=True)


def _access_dependency(
    security_dependencies: SecurityDependencies | None,
    permission: Permission,
    default_organization_id: str,
) -> Callable[..., AuthorizedRequest]:
    if security_dependencies is not None:
        return security_dependencies.authorized_request(permission)

    def development_access() -> AuthorizedRequest:
        return AuthorizedRequest(
            identity_id=None,
            principal=AuthenticatedPrincipal(
                subject="development-system",
                organization_id=default_organization_id,
                roles=frozenset({Role.ADMINISTRATOR}),
                display_name="Development system",
                provider="disabled",
            ),
        )

    return development_access
