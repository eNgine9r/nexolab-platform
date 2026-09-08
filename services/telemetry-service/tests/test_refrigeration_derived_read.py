from __future__ import annotations

from datetime import UTC, datetime, timedelta
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceRepository,
    ProfileAcceptanceAppendRequest,
)
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    AcquisitionSourceAppendRequest,
    CalibrationAppendRequest,
    InstrumentCreate,
    InstrumentUpdate,
    SignalCreate,
)
from app.model_registry import register_models
from app.refrigeration.calculation_policy import (
    CalculationPolicyCreateRequest,
    CalculationPolicyRepository,
)
from app.refrigeration.circuit_repository import RefrigerationCircuitRepository
from app.refrigeration.circuit_schemas import (
    CircuitBindingAppendRequest,
    CircuitConfigurationAppendRequest,
    CircuitCreateRequest,
)
from app.refrigeration.derived_read import (
    ALL_DERIVED_METRICS,
    HistoricalDerivedReadService,
)
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.refrigeration.property_provider import CANONICAL_PROPERTY_PROVIDER_PROFILE
from app.security.authorization import Role
from app.security.models import SecurityAuditEvent
from app.security.repository import AuditEventInput, SecurityRepository


ORG = "00000000-0000-0000-0000-000000000001"
OTHER_ORG = "22222222-2222-2222-2222-222222222222"
T0 = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=1)


def _equipment(
    equipment_id: str, organization_id: str = ORG
) -> RefrigerationEquipmentRecord:
    return RefrigerationEquipmentRecord(
        id=equipment_id,
        organization_id=organization_id,
        code=f"CODE-{equipment_id}",
        name=f"Equipment {equipment_id}",
        location="Lab",
        laboratory="Lab",
        zone=None,
        node_id=None,
        climate_chamber_id=None,
        equipment_type="Холодильна вітрина",
        manufacturer="Test",
        model="Test",
        serial_number=f"SN-{equipment_id}",
        temperature_class="3M1",
        installed_at=None,
        serviced_at=None,
        lifecycle_status="active",
        status="offline",
        average_temperature_c=0.0,
        min_temperature_c=0.0,
        max_temperature_c=0.0,
        online_sensors=0,
        total_sensors=48,
        active_alarms=0,
        last_seen_at=None,
        version=1,
        created_by="test-suite",
        created_at=T0,
        updated_at=T0,
        deleted_by=None,
        deleted_at=None,
    )


def _scope(tmp_path: Path, *, future_ms: int = 5000):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'derived-read.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG, slug="default", name="Default")
    security.provision_organization(
        organization_id=OTHER_ORG, slug="other", name="Other"
    )
    with Session(database.engine) as session:
        with session.begin():
            session.add_all(
                [_equipment("equipment-1"), _equipment("equipment-2", OTHER_ORG)]
            )

    circuits = RefrigerationCircuitRepository(database)
    instrumentation = InstrumentationRepository(database)
    profiles = AcquisitionProfileAcceptanceRepository(database)
    policies = CalculationPolicyRepository(database)
    policy = policies.create(
        CalculationPolicyCreateRequest(
            version="rfx08b-test-v1",
            maximum_age_ms=60_000,
            maximum_future_clock_skew_ms=future_ms,
            maximum_cross_input_skew_ms=60_000,
            accepted_calibration_states=["valid"],
            require_calibration_at_observation=False,
            calibration_required_roles=[],
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    circuit, _ = circuits.create_circuit(
        CircuitCreateRequest(
            equipment_id="equipment-1",
            business_key="CIRCUIT-1",
            display_name="Primary circuit",
            valid_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    circuits.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="R134A",
            calculation_policy_version=policy.version,
            property_provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE,
            valid_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    service = HistoricalDerivedReadService(
        database, circuits, instrumentation, profiles, policies
    )
    return database, circuits, instrumentation, profiles, policies, circuit, service


def _role(
    circuits: RefrigerationCircuitRepository,
    instrumentation: InstrumentationRepository,
    profiles: AcquisitionProfileAcceptanceRepository,
    circuit_id: str,
    *,
    role: str,
    quantity: str,
    unit: str,
    kind: str,
    pressure_reference: str | None = None,
    calibration_scope: str | None = None,
):
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key=f"INST-{role}",
            display_name=f"Instrument {role}",
            instrument_kind=kind,
            pressure_reference=pressure_reference,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    instrumentation.append_acceptance(
        instrument.id,
        AcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"SIG-{role}",
            display_name=f"Signal {role}",
            physical_quantity=quantity,
            engineering_unit=unit,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    source = instrumentation.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="equipment-1",
            channel_id=f"channel-{role}",
            metric=f"source.{role}",
            unit=unit,
            acquisition_profile_id=f"profile-{role}",
            acquisition_profile_version="1",
            calibration_scope=calibration_scope,
            valid_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    profiles.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    binding = circuits.append_binding(
        circuit_id,
        CircuitBindingAppendRequest(role=role, signal_id=signal.id, valid_from=T0),
        actor_id="test-suite",
        organization_id=ORG,
    )
    return instrument, signal, source, binding


def _sample(
    database: Database,
    source,
    *,
    captured_at: datetime,
    value: float,
    event_suffix: int,
    quality: str = "valid",
) -> str:
    event_id = str(UUID(int=event_suffix))
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                TelemetrySample(
                    event_id=event_id,
                    node_id=source.node_id,
                    captured_at=captured_at,
                    metric=source.metric,
                    value=value,
                    unit=source.unit,
                    quality=quality,
                    source="test",
                    equipment_id=source.equipment_id,
                    channel_id=source.channel_id,
                    alarm=None,
                    raw_value=None,
                    raw_status=None,
                    raw_payload={},
                    raw_payload_retained=True,
                    received_at=captured_at + timedelta(milliseconds=100),
                )
            )
    return event_id


def _all_roles(scope):
    _, circuits, instrumentation, profiles, _, circuit, _ = scope
    suction = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    condensing = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="condensing_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    suction_temp = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_line_temperature",
        quantity="temperature",
        unit="degC",
        kind="temperature_probe",
    )[2]
    liquid_temp = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="liquid_line_temperature",
        quantity="temperature",
        unit="degC",
        kind="temperature_probe",
    )[2]
    return suction, condensing, suction_temp, liquid_temp


def test_all_four_metrics_use_persisted_authoritative_sources(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    database, _, _, _, _, circuit, service = scope
    suction, condensing, suction_temp, liquid_temp = _all_roles(scope)
    captured = T0 + timedelta(seconds=10)
    ids = {
        _sample(database, suction, captured_at=captured, value=2.5, event_suffix=1),
        _sample(database, condensing, captured_at=captured, value=10.0, event_suffix=2),
        _sample(
            database, suction_temp, captured_at=captured, value=5.0, event_suffix=3
        ),
        _sample(
            database, liquid_temp, captured_at=captured, value=30.0, event_suffix=4
        ),
    }

    results = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        computed_at=T0 + timedelta(seconds=21),
    )

    assert tuple(item.metric for item in results) == ALL_DERIVED_METRICS
    assert all(item.availability == "available" for item in results)
    assert all(item.reason_codes == () for item in results)
    for item in results:
        assert item.kernel_result is not None
        assert item.kernel_result.context.calculation_policy_version == "rfx08b-test-v1"
        assert item.kernel_result.provider is not None
        assert (
            item.kernel_result.provider.provider_profile
            == CANONICAL_PROPERTY_PROVIDER_PROFILE
        )
        assert {source.event_id for source in item.kernel_result.sources} <= ids
        assert all(
            source.acquisition_source_id for source in item.kernel_result.sources
        )
        assert all(
            source.acquisition_acceptance_at_sample
            for source in item.kernel_result.sources
        )
        assert all(
            source.acquisition_acceptance_at_observation
            for source in item.kernel_result.sources
        )


def test_selector_prefers_at_or_before_and_event_id_desc_tie_break(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    captured = T0 + timedelta(seconds=10)
    lower = _sample(database, source, captured_at=captured, value=2.0, event_suffix=10)
    higher = _sample(database, source, captured_at=captured, value=2.5, event_suffix=11)
    _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=21),
        value=3.0,
        event_suffix=12,
    )

    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=22),
    )[0]
    assert item.availability == "available"
    assert item.kernel_result is not None
    assert item.kernel_result.sources[0].event_id == higher
    assert item.kernel_result.sources[0].event_id != lower


def test_future_candidate_is_not_selected_when_policy_disallows_future(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path, future_ms=0)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=21),
        value=2.5,
        event_suffix=20,
    )

    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=22),
    )[0]
    assert item.availability == "unavailable"
    assert item.reason_codes == ("raw_sample_unavailable",)
    assert item.kernel_result is None


def test_profile_acceptance_is_independent_at_observation_time(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    instrument, signal, source, _ = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )
    _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=10),
        value=2.5,
        event_suffix=30,
    )
    profiles.append(
        instrument.id,
        signal.id,
        source.id,
        ProfileAcceptanceAppendRequest(
            accepted_for_calculation=False,
            effective_from=T0 + timedelta(seconds=15),
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )

    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=22),
    )[0]
    assert item.availability == "unavailable"
    assert item.kernel_result is not None
    assert item.reason_codes == ("acquisition_not_accepted",)


def test_missing_policy_and_cross_org_access_fail_closed(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    _, circuits, _, _, _, circuit, service = scope
    circuits.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="R134A",
            calculation_policy_version="missing-policy",
            property_provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )

    missing = service.calculate(
        circuit.id,
        T0 + timedelta(hours=1, seconds=1),
        organization_id=ORG,
        metrics=["refrigeration.superheat"],
        computed_at=T0 + timedelta(hours=1, seconds=2),
    )[0]
    assert missing.reason_codes == ("calculation_policy_unresolved",)
    assert missing.kernel_result is None

    isolated = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=OTHER_ORG,
        metrics=["refrigeration.superheat"],
        computed_at=T0 + timedelta(seconds=21),
    )[0]
    assert isolated.reason_codes == ("circuit_lifecycle_unresolved",)
    assert isolated.kernel_result is None


def test_selector_does_not_skip_newer_bad_quality_for_older_valid_sample(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=10),
        value=2.0,
        event_suffix=201,
        quality="valid",
    )
    bad = _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=15),
        value=2.5,
        event_suffix=202,
        quality="sensor_error",
    )
    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=21),
    )[0]
    assert item.availability == "unavailable"
    assert item.reason_codes == ("telemetry_quality_rejected",)
    assert item.kernel_result is not None
    assert item.kernel_result.sources[0].event_id == bad


def test_selector_uses_nearest_future_then_event_id_desc(tmp_path: Path) -> None:
    scope = _scope(tmp_path, future_ms=5000)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    observation = T0 + timedelta(seconds=20)
    _sample(
        database,
        source,
        captured_at=observation + timedelta(seconds=4),
        value=3.0,
        event_suffix=210,
    )
    _sample(
        database,
        source,
        captured_at=observation + timedelta(seconds=2),
        value=2.0,
        event_suffix=211,
    )
    expected = _sample(
        database,
        source,
        captured_at=observation + timedelta(seconds=2),
        value=2.5,
        event_suffix=212,
    )
    item = service.calculate(
        circuit.id,
        observation,
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=observation + timedelta(seconds=5),
    )[0]
    assert item.availability == "available"
    assert item.kernel_result is not None
    assert item.kernel_result.sources[0].event_id == expected
    assert item.kernel_result.effective_at == observation


def test_new_configuration_epoch_excludes_pre_transition_sample(tmp_path: Path) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    source = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
    )[2]
    _sample(
        database,
        source,
        captured_at=T0 + timedelta(seconds=20),
        value=2.5,
        event_suffix=220,
    )
    circuits.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="R134A",
            calculation_policy_version="rfx08b-test-v1",
            property_provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE,
            valid_from=T0 + timedelta(seconds=30),
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=40),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=41),
    )[0]
    assert item.availability == "unavailable"
    assert item.reason_codes == ("raw_sample_unavailable",)
    assert item.kernel_result is None


def test_gauge_pressure_uses_historical_absolute_atmospheric_source(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, _, circuit, service = scope
    suction = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="gauge",
    )[2]
    atmosphere = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="atmospheric_pressure",
        quantity="pressure",
        unit="bar",
        kind="barometric_pressure_sensor",
        pressure_reference="absolute",
    )[2]
    captured = T0 + timedelta(seconds=10)
    _sample(database, suction, captured_at=captured, value=1.5, event_suffix=230)
    atmosphere_id = _sample(
        database, atmosphere, captured_at=captured, value=1.01, event_suffix=231
    )
    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=20),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=21),
    )[0]
    assert item.availability == "available"
    assert item.kernel_result is not None
    conversion = item.kernel_result.pressure_conversion
    assert conversion is not None
    assert conversion.atmospheric_event_id == atmosphere_id
    assert conversion.absolute_pressure_pa == 251000.0


def test_calibration_is_resolved_at_sample_and_observation_independently(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, circuits, instrumentation, profiles, policies, circuit, service = scope
    instrument, _, source, _ = _role(
        circuits,
        instrumentation,
        profiles,
        circuit.id,
        role="suction_pressure",
        quantity="pressure",
        unit="bar",
        kind="pressure_transmitter",
        pressure_reference="absolute",
        calibration_scope="instrument",
    )
    policies.create(
        CalculationPolicyCreateRequest(
            version="rfx08b-calibrated-v1",
            maximum_age_ms=60_000,
            maximum_future_clock_skew_ms=0,
            maximum_cross_input_skew_ms=60_000,
            accepted_calibration_states=["valid"],
            require_calibration_at_observation=True,
            calibration_required_roles=["suction_pressure"],
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    circuits.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="R134A",
            calculation_policy_version="rfx08b-calibrated-v1",
            property_provider_profile=CANONICAL_PROPERTY_PROVIDER_PROFILE,
            valid_from=T0 + timedelta(seconds=30),
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    instrumentation.append_calibration(
        instrument.id,
        CalibrationAppendRequest(
            calibration_scope="instrument",
            state="valid",
            valid_from=T0,
            certificate_reference="CAL-001",
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    sample_at = T0 + timedelta(seconds=35)
    _sample(database, source, captured_at=sample_at, value=2.5, event_suffix=240)
    instrumentation.append_calibration(
        instrument.id,
        CalibrationAppendRequest(
            calibration_scope="instrument",
            state="expired",
            valid_from=T0 + timedelta(seconds=38),
            certificate_reference="CAL-EXPIRED",
        ),
        actor_id="test-suite",
        organization_id=ORG,
    )
    item = service.calculate(
        circuit.id,
        T0 + timedelta(seconds=40),
        organization_id=ORG,
        metrics=["refrigeration.temperature.evaporation_saturation"],
        computed_at=T0 + timedelta(seconds=41),
    )[0]
    assert item.availability == "unavailable"
    assert item.reason_codes == ("calibration_state_rejected",)
    assert item.kernel_result is not None
    source_evidence = item.kernel_result.sources[0]
    assert source_evidence.calibration_at_sample is not None
    assert source_evidence.calibration_at_sample.state == "valid"
    assert source_evidence.calibration_at_observation is not None
    assert source_evidence.calibration_at_observation.state == "expired"


def test_historical_instrument_version_replays_from_immutable_audit_snapshot(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, _, instrumentation, _, _, _, service = scope
    security = SecurityRepository(database)
    create_event = AuditEventInput(
        organization_id=ORG,
        actor_identity_id=None,
        actor_subject="test-suite",
        actor_roles=frozenset({Role.ADMINISTRATOR}),
        action="instrument.created",
        entity_type="instrument",
        entity_id="pending",
    )
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key="AUDITED-INST",
            display_name="Version one",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
        organization_id=ORG,
        audit_repository=security,
        audit_event=create_event,
    )
    time.sleep(0.02)
    updated = instrumentation.update_instrument(
        instrument.id,
        InstrumentUpdate(
            inventory_key=instrument.inventory_key,
            display_name="Version two",
            instrument_kind=instrument.instrument_kind,
            manufacturer=None,
            model=None,
            serial_number=None,
            pressure_reference=None,
            lifecycle_state="active",
            metadata={},
        ),
        expected_version=1,
        actor_id="test-suite",
        organization_id=ORG,
        audit_repository=security,
        audit_event=AuditEventInput(
            organization_id=ORG,
            actor_identity_id=None,
            actor_subject="test-suite",
            actor_roles=frozenset({Role.ADMINISTRATOR}),
            action="instrument.updated",
            entity_type="instrument",
            entity_id=instrument.id,
        ),
    )
    with Session(database.engine) as session:
        events = list(
            session.query(SecurityAuditEvent)
            .filter(
                SecurityAuditEvent.organization_id == ORG,
                SecurityAuditEvent.entity_type == "instrument",
                SecurityAuditEvent.entity_id == instrument.id,
            )
            .order_by(SecurityAuditEvent.occurred_at.asc())
        )
    assert len(events) == 2
    created_at = events[0].occurred_at.replace(tzinfo=UTC)
    updated_at = events[1].occurred_at.replace(tzinfo=UTC)
    assert created_at < updated_at
    replay_at = created_at + (updated_at - created_at) / 2
    snapshot = service._instrument_snapshot_at(updated, replay_at, organization_id=ORG)
    assert snapshot is not None
    assert snapshot.version == 1


def test_historical_instrument_replay_uses_version_not_audit_uuid_for_equal_timestamp(
    tmp_path: Path,
) -> None:
    scope = _scope(tmp_path)
    database, _, instrumentation, _, _, _, service = scope
    security = SecurityRepository(database)
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key="AUDITED-TIE",
            display_name="Version one",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
        organization_id=ORG,
        audit_repository=security,
        audit_event=AuditEventInput(
            organization_id=ORG,
            actor_identity_id=None,
            actor_subject="test-suite",
            actor_roles=frozenset({Role.ADMINISTRATOR}),
            action="instrument.created",
            entity_type="instrument",
            entity_id="pending",
        ),
    )
    time.sleep(0.02)
    updated = instrumentation.update_instrument(
        instrument.id,
        InstrumentUpdate(
            inventory_key=instrument.inventory_key,
            display_name="Version two",
            instrument_kind=instrument.instrument_kind,
            manufacturer=None,
            model=None,
            serial_number=None,
            pressure_reference=None,
            lifecycle_state="active",
            metadata={},
        ),
        expected_version=1,
        actor_id="test-suite",
        organization_id=ORG,
        audit_repository=security,
        audit_event=AuditEventInput(
            organization_id=ORG,
            actor_identity_id=None,
            actor_subject="test-suite",
            actor_roles=frozenset({Role.ADMINISTRATOR}),
            action="instrument.updated",
            entity_type="instrument",
            entity_id=instrument.id,
        ),
    )
    created_at = instrument.created_at
    updated_at = updated.updated_at
    tie_at = created_at + (updated_at - created_at) / 2
    with Session(database.engine) as session:
        with session.begin():
            events = list(
                session.query(SecurityAuditEvent).filter(
                    SecurityAuditEvent.organization_id == ORG,
                    SecurityAuditEvent.entity_type == "instrument",
                    SecurityAuditEvent.entity_id == instrument.id,
                )
            )
            assert len(events) == 2
            for event in events:
                event.occurred_at = tie_at

    snapshot = service._instrument_snapshot_at(updated, tie_at, organization_id=ORG)
    assert snapshot is not None
    assert snapshot.version == 2
