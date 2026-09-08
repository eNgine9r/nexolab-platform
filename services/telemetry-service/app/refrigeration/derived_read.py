from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.instrumentation.models import (
    AnalogScalingProfileRecord,
    Instrument,
    InstrumentAcceptanceRecord,
    InstrumentCalibrationRecord,
    SignalAcquisitionSourceRecord,
)
from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceError,
    AcquisitionProfileAcceptanceRepository,
)
from app.instrumentation.repository import (
    InstrumentationRepository,
    InstrumentationRepositoryError,
)
from app.refrigeration.calculation_policy import (
    CalculationPolicyNotFoundError,
    CalculationPolicyRepository,
)
from app.refrigeration.circuit_models import RefrigerationCircuitConfigurationRecord
from app.refrigeration.circuit_repository import (
    CircuitDomainError,
    RefrigerationCircuitRepository,
    ResolvedCircuitBinding,
)
from app.refrigeration.derived_thermodynamics import (
    AcceptanceEvidence,
    CalculationContext,
    CalculationPolicy,
    CalibrationEvidence,
    DerivedResult,
    DerivedThermodynamicsKernel,
    MetricId,
    ResolvedSourceEvidence,
)
from app.refrigeration.property_provider import (
    CANONICAL_PROPERTY_PROVIDER_PROFILE,
    PropertyProviderError,
    create_refrigerant_property_provider,
)
from app.security.models import SecurityAuditEvent


ALL_DERIVED_METRICS: tuple[MetricId, ...] = (
    "refrigeration.temperature.evaporation_saturation",
    "refrigeration.temperature.condensation_saturation",
    "refrigeration.superheat",
    "refrigeration.subcooling",
)

OrchestrationReason = Literal[
    "invalid_observation_timestamp",
    "circuit_lifecycle_unresolved",
    "circuit_not_active",
    "circuit_configuration_unresolved",
    "calculation_policy_unresolved",
    "property_provider_profile_unresolved",
    "property_provider_unavailable",
    "binding_unresolved",
    "acquisition_source_unresolved",
    "raw_sample_unavailable",
    "instrument_version_unresolved",
]

_BASE_ROLES: dict[MetricId, tuple[str, ...]] = {
    "refrigeration.temperature.evaporation_saturation": ("suction_pressure",),
    "refrigeration.temperature.condensation_saturation": ("condensing_pressure",),
    "refrigeration.superheat": ("suction_pressure", "suction_line_temperature"),
    "refrigeration.subcooling": ("condensing_pressure", "liquid_line_temperature"),
}


@dataclass(frozen=True, slots=True)
class DerivedReadItem:
    metric: MetricId
    availability: Literal["available", "unavailable"]
    reason_codes: tuple[str, ...]
    observation_at: datetime
    computed_at: datetime
    kernel_result: DerivedResult | None


@dataclass(frozen=True, slots=True)
class _InstrumentSnapshot:
    version: int
    pressure_reference: str | None


class HistoricalDerivedReadService:
    """Assemble historical authoritative evidence and invoke the pure RFX-08A kernel."""

    def __init__(
        self,
        database: Database,
        circuit_repository: RefrigerationCircuitRepository,
        instrumentation_repository: InstrumentationRepository,
        profile_acceptance_repository: AcquisitionProfileAcceptanceRepository,
        calculation_policy_repository: CalculationPolicyRepository,
    ) -> None:
        self._engine = database.engine
        self._circuits = circuit_repository
        self._instrumentation = instrumentation_repository
        self._profile_acceptance = profile_acceptance_repository
        self._policies = calculation_policy_repository
        self._provider = None

    def calculate(
        self,
        circuit_id: str,
        observation_at: datetime,
        *,
        organization_id: str,
        metrics: Sequence[MetricId] | None = None,
        computed_at: datetime | None = None,
    ) -> tuple[DerivedReadItem, ...]:
        requested = _normalize_metrics(metrics)
        resolved_computed_at = _as_utc(computed_at or datetime.now(UTC))
        if not _aware(observation_at):
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "invalid_observation_timestamp",
            )
        observation_at = _as_utc(observation_at)

        try:
            lifecycle = self._circuits.resolve_lifecycle(
                circuit_id, observation_at, organization_id=organization_id
            )
        except (CircuitDomainError, ValueError):
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "circuit_lifecycle_unresolved",
            )
        if lifecycle.state != "active":
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "circuit_not_active",
            )

        try:
            configuration = self._circuits.resolve_configuration(
                circuit_id, observation_at, organization_id=organization_id
            )
        except (CircuitDomainError, ValueError):
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "circuit_configuration_unresolved",
            )

        try:
            policy = self._policies.as_kernel_policy(
                configuration.calculation_policy_version,
                organization_id=organization_id,
            )
        except (CalculationPolicyNotFoundError, ValueError):
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "calculation_policy_unresolved",
            )

        profile = (configuration.property_provider_profile or "").strip()
        if profile != CANONICAL_PROPERTY_PROVIDER_PROFILE:
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "property_provider_profile_unresolved",
            )
        try:
            provider = self._property_provider(profile)
        except PropertyProviderError:
            return self._all_unavailable(
                requested,
                observation_at,
                resolved_computed_at,
                "property_provider_unavailable",
            )

        context = CalculationContext(
            circuit_id=circuit_id,
            lifecycle_record_id=lifecycle.id,
            lifecycle_revision=lifecycle.revision,
            lifecycle_state=lifecycle.state,
            lifecycle_valid_from=_as_utc(lifecycle.valid_from),
            lifecycle_valid_to=_optional_utc(lifecycle.valid_to),
            configuration_record_id=configuration.id,
            configuration_revision=configuration.revision,
            configuration_valid_from=_as_utc(configuration.valid_from),
            configuration_valid_to=_optional_utc(configuration.valid_to),
            refrigerant_code=configuration.refrigerant_code,
            calculation_policy_version=configuration.calculation_policy_version,
            property_provider_profile=profile,
        )
        kernel = DerivedThermodynamicsKernel(provider)
        return tuple(
            self._calculate_metric(
                metric,
                circuit_id=circuit_id,
                organization_id=organization_id,
                observation_at=observation_at,
                computed_at=resolved_computed_at,
                configuration=configuration,
                context=context,
                policy=policy,
                kernel=kernel,
            )
            for metric in requested
        )

    def _calculate_metric(
        self,
        metric: MetricId,
        *,
        circuit_id: str,
        organization_id: str,
        observation_at: datetime,
        computed_at: datetime,
        configuration: RefrigerationCircuitConfigurationRecord,
        context: CalculationContext,
        policy: CalculationPolicy,
        kernel: DerivedThermodynamicsKernel,
    ) -> DerivedReadItem:
        evidence: list[ResolvedSourceEvidence] = []
        pressure_reference: str | None = None
        for role in _BASE_ROLES[metric]:
            source, reason = self._source_evidence(
                circuit_id,
                role,
                organization_id=organization_id,
                observation_at=observation_at,
                configuration=configuration,
                policy=policy,
            )
            if reason is not None:
                return _pre_kernel_unavailable(
                    metric, observation_at, computed_at, reason
                )
            assert source is not None
            evidence.append(source)
            if role in {"suction_pressure", "condensing_pressure"}:
                pressure_reference = source.pressure_reference

        if pressure_reference == "gauge":
            atmosphere, reason = self._source_evidence(
                circuit_id,
                "atmospheric_pressure",
                organization_id=organization_id,
                observation_at=observation_at,
                configuration=configuration,
                policy=policy,
            )
            if reason is not None:
                return _pre_kernel_unavailable(
                    metric, observation_at, computed_at, reason
                )
            assert atmosphere is not None
            evidence.append(atmosphere)

        result = kernel.calculate(
            metric,
            context=context,
            policy=policy,
            observation_at=observation_at,
            computed_at=computed_at,
            sources=evidence,
        )
        return DerivedReadItem(
            metric=metric,
            availability=result.availability,
            reason_codes=result.reason_codes,
            observation_at=observation_at,
            computed_at=computed_at,
            kernel_result=result,
        )

    def _source_evidence(
        self,
        circuit_id: str,
        role: str,
        *,
        organization_id: str,
        observation_at: datetime,
        configuration: RefrigerationCircuitConfigurationRecord,
        policy: CalculationPolicy,
    ) -> tuple[ResolvedSourceEvidence | None, OrchestrationReason | None]:
        try:
            binding = self._circuits.resolve_binding_identity(
                circuit_id, role, observation_at, organization_id=organization_id
            )
        except (CircuitDomainError, ValueError):
            return None, "binding_unresolved"

        instrument = binding.instrument
        signal = binding.signal
        try:
            acquisition = self._instrumentation.resolve_acquisition_source(
                instrument.id,
                signal.id,
                observation_at,
                organization_id=organization_id,
            )
        except (InstrumentationRepositoryError, ValueError):
            return None, "acquisition_source_unresolved"

        try:
            scaling = self._scaling_profile_at(
                signal.id,
                acquisition,
                observation_at,
                organization_id=organization_id,
            )
        except ValueError:
            return None, "acquisition_source_unresolved"
        sample = self._select_raw_sample(
            acquisition,
            binding,
            configuration,
            observation_at,
            scaling=scaling,
            allow_future=policy.maximum_future_clock_skew.total_seconds() > 0,
        )
        if sample is None:
            return None, "raw_sample_unavailable"

        instrument_snapshot = self._instrument_snapshot_at(
            instrument, sample.captured_at, organization_id=organization_id
        )
        if instrument_snapshot is None:
            return None, "instrument_version_unresolved"

        sample_at = _as_utc(sample.captured_at)
        instrument_sample = self._instrument_acceptance(
            instrument.id, sample_at, organization_id
        )
        instrument_observation = self._instrument_acceptance(
            instrument.id, observation_at, organization_id
        )
        scaling_id = scaling.id if scaling is not None else None
        acquisition_sample = self._profile_acceptance_at(
            instrument.id,
            signal.id,
            acquisition.id,
            sample_at,
            organization_id,
            scaling_id,
        )
        acquisition_observation = self._profile_acceptance_at(
            instrument.id,
            signal.id,
            acquisition.id,
            observation_at,
            organization_id,
            scaling_id,
        )

        calibration_scope = _text(acquisition.calibration_scope)
        if calibration_scope is None and scaling is not None:
            calibration_scope = _text(scaling.calibration_scope)
        calibration_sample = None
        calibration_observation = None
        if role in policy.calibration_required_roles and calibration_scope is not None:
            calibration_sample = self._calibration(
                instrument.id,
                sample_at,
                calibration_scope,
                organization_id,
            )
            if policy.require_calibration_at_observation:
                calibration_observation = self._calibration(
                    instrument.id,
                    observation_at,
                    calibration_scope,
                    organization_id,
                )

        return (
            ResolvedSourceEvidence(
                role=role,
                signal_id=signal.id,
                binding_id=binding.binding.id,
                binding_revision=binding.binding.revision,
                binding_valid_from=_as_utc(binding.binding.valid_from),
                binding_valid_to=_optional_utc(binding.binding.valid_to),
                event_id=sample.event_id,
                captured_at=_as_utc(sample.captured_at),
                value=sample.value,
                unit=sample.unit,
                quality=sample.quality,
                instrument_id=instrument.id,
                instrument_version=instrument_snapshot.version,
                pressure_reference=instrument_snapshot.pressure_reference,
                acquisition_profile_id=_text(acquisition.acquisition_profile_id),
                acquisition_profile_version=_text(
                    acquisition.acquisition_profile_version
                ),
                instrument_acceptance_at_sample=instrument_sample,
                instrument_acceptance_at_observation=instrument_observation,
                acquisition_acceptance_at_sample=acquisition_sample,
                acquisition_acceptance_at_observation=acquisition_observation,
                acquisition_source_id=acquisition.id,
                acquisition_source_revision=acquisition.revision,
                acquisition_source_valid_from=_as_utc(acquisition.valid_from),
                acquisition_source_valid_to=_optional_utc(acquisition.valid_to),
                scaling_profile_id=scaling_id,
                scaling_profile_revision=(
                    scaling.revision if scaling is not None else None
                ),
                scaling_profile_valid_from=(
                    _as_utc(scaling.effective_from) if scaling is not None else None
                ),
                scaling_profile_valid_to=(
                    _optional_utc(scaling.effective_to) if scaling is not None else None
                ),
                calibration_scope=calibration_scope,
                calibration_at_sample=calibration_sample,
                calibration_at_observation=calibration_observation,
            ),
            None,
        )

    def _scaling_profile_at(
        self,
        signal_id: str,
        acquisition: SignalAcquisitionSourceRecord,
        at: datetime,
        *,
        organization_id: str,
    ) -> AnalogScalingProfileRecord | None:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(AnalogScalingProfileRecord).where(
                        AnalogScalingProfileRecord.organization_id == organization_id,
                        AnalogScalingProfileRecord.signal_id == signal_id,
                        AnalogScalingProfileRecord.acquisition_source_id
                        == acquisition.id,
                        AnalogScalingProfileRecord.effective_from <= at,
                        or_(
                            AnalogScalingProfileRecord.effective_to.is_(None),
                            AnalogScalingProfileRecord.effective_to > at,
                        ),
                    )
                )
            )
            if len(rows) > 1:
                raise ValueError(
                    "analog scaling history is ambiguous at observation time"
                )
            if not rows:
                has_scaling_history = session.scalar(
                    select(AnalogScalingProfileRecord.id)
                    .where(
                        AnalogScalingProfileRecord.organization_id == organization_id,
                        AnalogScalingProfileRecord.signal_id == signal_id,
                        AnalogScalingProfileRecord.acquisition_source_id
                        == acquisition.id,
                        AnalogScalingProfileRecord.effective_from <= at,
                    )
                    .limit(1)
                )
                if has_scaling_history is not None:
                    raise ValueError(
                        "analog scaling history exists but no profile is effective at observation time"
                    )
                return None
            row = rows[0]
            if _text(row.acquisition_profile_id) != _text(
                acquisition.acquisition_profile_id
            ) or _text(row.acquisition_profile_version) != _text(
                acquisition.acquisition_profile_version
            ):
                raise ValueError(
                    "analog scaling profile identity does not match acquisition source"
                )
            session.expunge(row)
            return row

    def _select_raw_sample(
        self,
        source: SignalAcquisitionSourceRecord,
        binding: ResolvedCircuitBinding,
        configuration: RefrigerationCircuitConfigurationRecord,
        observation_at: datetime,
        *,
        scaling: AnalogScalingProfileRecord | None,
        allow_future: bool,
    ) -> TelemetrySample | None:
        starts = [
            _as_utc(binding.binding.valid_from),
            _as_utc(configuration.valid_from),
            _as_utc(source.valid_from),
        ]
        ends = [
            _optional_utc(binding.binding.valid_to),
            _optional_utc(configuration.valid_to),
            _optional_utc(source.valid_to),
        ]
        if scaling is not None:
            starts.append(_as_utc(scaling.effective_from))
            ends.append(_optional_utc(scaling.effective_to))
        start = max(starts)
        bounded_ends = [value for value in ends if value is not None]
        end = min(bounded_ends) if bounded_ends else None
        if end is not None and start >= end:
            return None

        interval = [
            TelemetrySample.node_id == source.node_id,
            TelemetrySample.equipment_id == source.equipment_id,
            TelemetrySample.channel_id == source.channel_id,
            TelemetrySample.metric == source.metric,
            TelemetrySample.unit == source.unit,
            TelemetrySample.captured_at >= start,
        ]
        if end is not None:
            interval.append(TelemetrySample.captured_at < end)
        with Session(self._engine, expire_on_commit=False) as session:
            prior = session.scalar(
                select(TelemetrySample)
                .where(*interval, TelemetrySample.captured_at <= observation_at)
                .order_by(
                    TelemetrySample.captured_at.desc(), TelemetrySample.event_id.desc()
                )
                .limit(1)
            )
            if prior is not None:
                session.expunge(prior)
                return prior
            if not allow_future:
                return None
            future = session.scalar(
                select(TelemetrySample)
                .where(*interval, TelemetrySample.captured_at > observation_at)
                .order_by(
                    TelemetrySample.captured_at.asc(), TelemetrySample.event_id.desc()
                )
                .limit(1)
            )
            if future is not None:
                session.expunge(future)
            return future

    def _instrument_snapshot_at(
        self,
        instrument: Instrument,
        at: datetime,
        *,
        organization_id: str,
    ) -> _InstrumentSnapshot | None:
        resolved_at = _as_utc(at)
        created_at = _as_utc(instrument.created_at)
        updated_at = _as_utc(instrument.updated_at)
        if created_at > resolved_at:
            return None
        if updated_at <= resolved_at:
            return _InstrumentSnapshot(
                version=instrument.version,
                pressure_reference=instrument.pressure_reference,
            )
        with Session(self._engine, expire_on_commit=False) as session:
            events = list(
                session.scalars(
                    select(SecurityAuditEvent).where(
                        SecurityAuditEvent.organization_id == organization_id,
                        SecurityAuditEvent.entity_type == "instrument",
                        SecurityAuditEvent.entity_id == instrument.id,
                        SecurityAuditEvent.action.in_(
                            ("instrument.created", "instrument.updated")
                        ),
                        SecurityAuditEvent.occurred_at <= resolved_at,
                        SecurityAuditEvent.after_snapshot.is_not(None),
                    )
                )
            )

        candidates: list[_InstrumentSnapshot] = []
        for event in events:
            if not isinstance(event.after_snapshot, dict):
                continue
            snapshot = event.after_snapshot
            version = snapshot.get("version")
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version < 1
                or version > instrument.version
                or snapshot.get("id") != instrument.id
                or snapshot.get("inventory_key") != instrument.inventory_key
                or snapshot.get("instrument_kind") != instrument.instrument_kind
            ):
                continue
            pressure_reference = snapshot.get("pressure_reference")
            if pressure_reference not in {None, "absolute", "gauge"}:
                continue
            candidates.append(
                _InstrumentSnapshot(
                    version=version, pressure_reference=pressure_reference
                )
            )

        if not candidates:
            return None
        highest_version = max(candidate.version for candidate in candidates)
        highest = [
            candidate
            for candidate in candidates
            if candidate.version == highest_version
        ]
        if len(highest) != 1:
            return None
        return highest[0]

    def _instrument_acceptance(
        self, instrument_id: str, at: datetime, organization_id: str
    ) -> AcceptanceEvidence | None:
        try:
            row = self._instrumentation.resolve_acceptance(
                instrument_id, at, organization_id=organization_id
            )
        except (InstrumentationRepositoryError, ValueError):
            return None
        return _acceptance_evidence(row)

    def _profile_acceptance_at(
        self,
        instrument_id: str,
        signal_id: str,
        acquisition_source_id: str,
        at: datetime,
        organization_id: str,
        scaling_profile_id: str | None,
    ) -> AcceptanceEvidence | None:
        try:
            row = self._profile_acceptance.resolve(
                instrument_id,
                signal_id,
                acquisition_source_id,
                at,
                scaling_profile_id=scaling_profile_id,
                organization_id=organization_id,
            )
        except AcquisitionProfileAcceptanceError:
            return None
        return AcceptanceEvidence(
            record_id=row.id,
            revision=row.revision,
            schema_version=row.schema_version,
            accepted_for_calculation=row.accepted_for_calculation,
            valid_from=_as_utc(row.effective_from),
            valid_to=_optional_utc(row.effective_to),
        )

    def _calibration(
        self,
        instrument_id: str,
        at: datetime,
        scope: str,
        organization_id: str,
    ) -> CalibrationEvidence | None:
        try:
            row = self._instrumentation.resolve_calibration(
                instrument_id,
                at,
                calibration_scope=scope,
                organization_id=organization_id,
            )
        except (InstrumentationRepositoryError, ValueError):
            return None
        return _calibration_evidence(row)

    def _property_provider(self, profile: str):
        if self._provider is None:
            self._provider = create_refrigerant_property_provider(profile)
        return self._provider

    @staticmethod
    def _all_unavailable(
        metrics: Sequence[MetricId],
        observation_at: datetime,
        computed_at: datetime,
        reason: OrchestrationReason,
    ) -> tuple[DerivedReadItem, ...]:
        return tuple(
            _pre_kernel_unavailable(metric, observation_at, computed_at, reason)
            for metric in metrics
        )


def _acceptance_evidence(row: InstrumentAcceptanceRecord) -> AcceptanceEvidence:
    return AcceptanceEvidence(
        record_id=row.id,
        revision=row.revision,
        schema_version=row.schema_version,
        accepted_for_calculation=row.accepted_for_calculation,
        valid_from=_as_utc(row.effective_from),
        valid_to=_optional_utc(row.effective_to),
    )


def _calibration_evidence(row: InstrumentCalibrationRecord) -> CalibrationEvidence:
    return CalibrationEvidence(
        record_id=row.id,
        revision=row.revision,
        schema_version=row.schema_version,
        state=row.state,
        valid_from=_as_utc(row.valid_from),
        valid_to=_optional_utc(row.valid_to),
        certificate_reference=row.certificate_reference,
    )


def _pre_kernel_unavailable(
    metric: MetricId,
    observation_at: datetime,
    computed_at: datetime,
    reason: OrchestrationReason,
) -> DerivedReadItem:
    return DerivedReadItem(
        metric=metric,
        availability="unavailable",
        reason_codes=(reason,),
        observation_at=observation_at,
        computed_at=computed_at,
        kernel_result=None,
    )


def _normalize_metrics(metrics: Sequence[MetricId] | None) -> tuple[MetricId, ...]:
    if metrics is None:
        return ALL_DERIVED_METRICS
    requested = set(metrics)
    unknown = requested.difference(ALL_DERIVED_METRICS)
    if unknown:
        raise ValueError(f"unsupported derived metrics: {sorted(unknown)!r}")
    return tuple(metric for metric in ALL_DERIVED_METRICS if metric in requested)


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_utc(value: datetime | None) -> datetime | None:
    return _as_utc(value) if value is not None else None
