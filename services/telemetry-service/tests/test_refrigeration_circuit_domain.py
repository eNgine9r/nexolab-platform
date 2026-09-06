from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import Instrument, Signal
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import AcceptanceAppendRequest, InstrumentCreate, SignalCreate
from app.model_registry import register_models
from app.refrigeration.circuit_repository import (
    CircuitBindingCompatibilityError,
    CircuitEquipmentNotFoundError,
    CircuitHistoryOrderError,
    CircuitResolutionError,
    RefrigerationCircuitRepository,
)
from app.refrigeration.circuit_schemas import (
    CircuitBindingAppendRequest,
    CircuitConfigurationAppendRequest,
    CircuitCreateRequest,
    CircuitLifecycleAppendRequest,
)
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"
T0 = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)


def _equipment(equipment_id: str, organization_id: str = ORGANIZATION_ID) -> RefrigerationEquipmentRecord:
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


def _repositories(tmp_path: Path):
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'rfx06.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID, slug="default", name="Default"
    )
    security.provision_organization(
        organization_id=OTHER_ORGANIZATION_ID, slug="other", name="Other"
    )
    with Session(database.engine) as session:
        with session.begin():
            session.add_all(
                [
                    _equipment("equipment-1"),
                    _equipment("equipment-other", OTHER_ORGANIZATION_ID),
                ]
            )
    return database, RefrigerationCircuitRepository(database), InstrumentationRepository(database)


def _circuit(repository: RefrigerationCircuitRepository):
    circuit, lifecycle = repository.create_circuit(
        CircuitCreateRequest(
            equipment_id="equipment-1",
            business_key="CIRCUIT-1",
            display_name="Primary circuit",
            valid_from=T0,
        ),
        actor_id="test-suite",
    )
    return circuit, lifecycle


def _accepted_signal(
    instrumentation: InstrumentationRepository,
    *,
    key: str,
    kind: str,
    quantity: str,
    unit: str,
    pressure_reference: str | None = None,
):
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key=f"INST-{key}",
            display_name=f"Instrument {key}",
            instrument_kind=kind,
            pressure_reference=pressure_reference,
        ),
        actor_id="test-suite",
    )
    instrumentation.append_acceptance(
        instrument.id,
        AcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="test-suite",
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"SIG-{key}",
            display_name=f"Signal {key}",
            physical_quantity=quantity,
            engineering_unit=unit,
        ),
        actor_id="test-suite",
    )
    return instrument, signal


def test_circuit_lifecycle_is_historical_and_calculation_enabled_is_derived(tmp_path: Path) -> None:
    _, repository, _ = _repositories(tmp_path)
    circuit, initial = _circuit(repository)

    assert initial.state == "active"
    assert repository.resolve_lifecycle(circuit.id, T0 + timedelta(hours=1)).state == "active"

    inactive = repository.append_lifecycle(
        circuit.id,
        CircuitLifecycleAppendRequest(
            state="inactive",
            valid_from=T0 + timedelta(days=1),
        ),
        actor_id="operator",
    )
    history = repository.list_lifecycle_history(circuit.id)

    assert [row.state for row in history] == ["active", "inactive"]
    assert history[0].valid_to is not None
    assert history[0].valid_to.replace(tzinfo=UTC) == inactive.valid_from
    assert repository.resolve_lifecycle(circuit.id, T0 + timedelta(hours=23)).state == "active"
    assert repository.resolve_lifecycle(circuit.id, inactive.valid_from).state == "inactive"

    with pytest.raises(CircuitHistoryOrderError):
        repository.append_lifecycle(
            circuit.id,
            CircuitLifecycleAppendRequest(
                state="retired",
                valid_from=T0 + timedelta(hours=12),
            ),
            actor_id="operator",
        )


def test_configuration_resolves_as_of_without_current_fallback(tmp_path: Path) -> None:
    _, repository, _ = _repositories(tmp_path)
    circuit, _ = _circuit(repository)

    with pytest.raises(CircuitResolutionError):
        repository.resolve_configuration(circuit.id, T0 + timedelta(hours=1))

    first = repository.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="r404a",
            calculation_policy_version="rfx06-config-v1",
            valid_from=T0 + timedelta(days=1),
        ),
        actor_id="operator",
    )
    second = repository.append_configuration(
        circuit.id,
        CircuitConfigurationAppendRequest(
            refrigerant_code="R448A",
            calculation_policy_version="rfx06-config-v2",
            valid_from=T0 + timedelta(days=2),
        ),
        actor_id="operator",
    )

    assert first.refrigerant_code == "R404A"
    assert first.property_provider_profile is None
    assert repository.resolve_configuration(
        circuit.id, T0 + timedelta(days=1, hours=12)
    ).id == first.id
    assert repository.resolve_configuration(circuit.id, second.valid_from).id == second.id


def test_semantic_binding_preserves_gauge_pressure_and_requires_accepted_authority(
    tmp_path: Path,
) -> None:
    _, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    gauge_instrument, gauge_signal = _accepted_signal(
        instrumentation,
        key="SUCTION",
        kind="pressure_transmitter",
        quantity="pressure",
        unit="bar",
        pressure_reference="gauge",
    )

    bound = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="suction_pressure",
            signal_id=gauge_signal.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator",
    )

    assert bound.binding.signal_id == gauge_signal.id
    assert bound.instrument.id == gauge_instrument.id
    assert bound.instrument.pressure_reference == "gauge"
    assert bound.signal.engineering_unit == "bar"
    resolved = repository.resolve_binding(
        circuit.id, "suction_pressure", T0 + timedelta(hours=2)
    )
    assert resolved.binding.id == bound.binding.id
    assert resolved.instrument.pressure_reference == "gauge"

    unaccepted = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key="INST-UNACCEPTED",
            display_name="Unaccepted temperature probe",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
    )
    unaccepted_signal = instrumentation.create_signal(
        unaccepted.id,
        SignalCreate(
            business_key="SIG-UNACCEPTED",
            display_name="Unaccepted temperature",
            physical_quantity="temperature",
            engineering_unit="degC",
        ),
        actor_id="test-suite",
    )
    with pytest.raises(CircuitBindingCompatibilityError):
        repository.append_binding(
            circuit.id,
            CircuitBindingAppendRequest(
                role="suction_line_temperature",
                signal_id=unaccepted_signal.id,
                valid_from=T0 + timedelta(hours=1),
            ),
            actor_id="operator",
        )


def test_atmospheric_role_rejects_gauge_and_accepts_only_absolute_barometric_source(
    tmp_path: Path,
) -> None:
    _, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    _, gauge_signal = _accepted_signal(
        instrumentation,
        key="GAUGE-ATM",
        kind="pressure_transmitter",
        quantity="pressure",
        unit="bar",
        pressure_reference="gauge",
    )
    with pytest.raises(CircuitBindingCompatibilityError):
        repository.append_binding(
            circuit.id,
            CircuitBindingAppendRequest(
                role="atmospheric_pressure",
                signal_id=gauge_signal.id,
                valid_from=T0 + timedelta(hours=1),
            ),
            actor_id="operator",
        )

    _, absolute_signal = _accepted_signal(
        instrumentation,
        key="ATM",
        kind="barometric_pressure_sensor",
        quantity="pressure",
        unit="kPa",
        pressure_reference="absolute",
    )
    bound = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="atmospheric_pressure",
            signal_id=absolute_signal.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator",
    )
    assert bound.signal.engineering_unit == "kPa"
    assert bound.instrument.pressure_reference == "absolute"


def test_temperature_and_humidity_roles_fail_closed_on_incompatible_units(tmp_path: Path) -> None:
    _, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    _, bad_temperature = _accepted_signal(
        instrumentation,
        key="TEMP-BAD-UNIT",
        kind="temperature_probe",
        quantity="temperature",
        unit="bar",
    )
    with pytest.raises(CircuitBindingCompatibilityError):
        repository.append_binding(
            circuit.id,
            CircuitBindingAppendRequest(
                role="liquid_line_temperature",
                signal_id=bad_temperature.id,
                valid_from=T0 + timedelta(hours=1),
            ),
            actor_id="operator",
        )

    _, humidity = _accepted_signal(
        instrumentation,
        key="RH",
        kind="humidity_transmitter",
        quantity="relative_humidity",
        unit="%RH",
    )
    bound = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="relative_humidity",
            signal_id=humidity.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator",
    )
    assert bound.signal.engineering_unit == "%RH"


def test_historical_binding_resolution_uses_as_of_acceptance_not_current_lifecycle(
    tmp_path: Path,
) -> None:
    database, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    instrument, signal = _accepted_signal(
        instrumentation,
        key="HISTORICAL",
        kind="temperature_probe",
        quantity="temperature",
        unit="degC",
    )
    bound = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="suction_line_temperature",
            signal_id=signal.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator",
    )

    with Session(database.engine) as session, session.begin():
        stored_instrument = session.get(Instrument, instrument.id)
        stored_signal = session.get(Signal, signal.id)
        assert stored_instrument is not None and stored_signal is not None
        stored_instrument.lifecycle_state = "retired"
        stored_signal.lifecycle_state = "retired"

    resolved = repository.resolve_binding(
        circuit.id, "suction_line_temperature", T0 + timedelta(hours=1, minutes=30)
    )
    assert resolved.binding.id == bound.binding.id
    with pytest.raises(CircuitBindingCompatibilityError):
        repository.append_binding(
            circuit.id,
            CircuitBindingAppendRequest(
                role="liquid_line_temperature",
                signal_id=signal.id,
                valid_from=T0 + timedelta(hours=2),
            ),
            actor_id="operator",
        )


def test_binding_handover_closes_previous_interval_with_operator_provenance(
    tmp_path: Path,
) -> None:
    _, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    _, first_signal = _accepted_signal(
        instrumentation,
        key="HANDOVER-1",
        kind="temperature_probe",
        quantity="temperature",
        unit="degC",
    )
    _, second_signal = _accepted_signal(
        instrumentation,
        key="HANDOVER-2",
        kind="temperature_probe",
        quantity="temperature",
        unit="degC",
    )
    first = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="suction_line_temperature",
            signal_id=first_signal.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator-a",
    )
    second = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="suction_line_temperature",
            signal_id=second_signal.id,
            valid_from=T0 + timedelta(hours=2),
        ),
        actor_id="operator-b",
    )

    history = repository.list_bindings(circuit.id, include_history=True)
    previous = next(item for item in history if item.binding.id == first.binding.id)
    assert previous.binding.valid_to is not None
    assert previous.binding.valid_to.replace(tzinfo=UTC) == second.binding.valid_from
    assert previous.binding.ended_by == "operator-b"
    assert previous.binding.ended_at is not None
    assert repository.resolve_binding(
        circuit.id, "suction_line_temperature", T0 + timedelta(hours=2)
    ).binding.id == second.binding.id


def test_binding_can_end_without_synthetic_replacement_and_then_resolves_unavailable(
    tmp_path: Path,
) -> None:
    _, repository, instrumentation = _repositories(tmp_path)
    circuit, _ = _circuit(repository)
    _, signal = _accepted_signal(
        instrumentation,
        key="TEMP-END",
        kind="temperature_probe",
        quantity="temperature",
        unit="degC",
    )
    bound = repository.append_binding(
        circuit.id,
        CircuitBindingAppendRequest(
            role="suction_line_temperature",
            signal_id=signal.id,
            valid_from=T0 + timedelta(hours=1),
        ),
        actor_id="operator",
    )
    ended = repository.end_binding(
        circuit.id,
        "suction_line_temperature",
        T0 + timedelta(hours=2),
        actor_id="operator",
    )
    assert ended.binding.id == bound.binding.id
    assert ended.binding.ended_by == "operator"
    with pytest.raises(CircuitResolutionError):
        repository.resolve_binding(
            circuit.id, "suction_line_temperature", T0 + timedelta(hours=3)
        )


def test_cross_organization_equipment_link_fails_closed(tmp_path: Path) -> None:
    _, repository, _ = _repositories(tmp_path)

    with pytest.raises(CircuitEquipmentNotFoundError):
        repository.create_circuit(
            CircuitCreateRequest(
                equipment_id="equipment-other",
                business_key="CROSS",
                display_name="Cross organization",
                valid_from=T0,
            ),
            actor_id="test-suite",
            organization_id=ORGANIZATION_ID,
        )
