from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import AcceptanceAppendRequest, InstrumentCreate, SignalCreate
from app.refrigeration.circuit_repository import RefrigerationCircuitRepository
from app.refrigeration.circuit_schemas import (
    CircuitBindingAppendRequest,
    CircuitConfigurationAppendRequest,
    CircuitCreateRequest,
)
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.repository import SecurityRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for circuit-domain constraint validation",
)

T0 = datetime(2026, 9, 6, 0, 0, tzinfo=UTC)
TABLES = {
    "refrigeration_circuits",
    "refrigeration_circuit_lifecycle_history",
    "refrigeration_circuit_configuration_history",
    "refrigeration_circuit_signal_bindings",
}


def _equipment(equipment_id: str, organization_id: str) -> RefrigerationEquipmentRecord:
    return RefrigerationEquipmentRecord(
        id=equipment_id,
        organization_id=organization_id,
        code=f"RFX06-{equipment_id}",
        name=f"RFX06 {equipment_id}",
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


def _scope() -> tuple[Database, SecurityRepository, RefrigerationCircuitRepository, InstrumentationRepository, str, str]:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    organization_id = str(uuid4())
    equipment_id = str(uuid4())
    suffix = uuid4().hex
    security.provision_organization(
        organization_id=organization_id,
        slug=f"rfx06-{suffix}",
        name="RFX06 PostgreSQL organization",
    )
    with Session(database.engine) as session:
        with session.begin():
            session.add(_equipment(equipment_id, organization_id))
    return (
        database,
        security,
        RefrigerationCircuitRepository(database),
        InstrumentationRepository(database),
        organization_id,
        equipment_id,
    )


def _accepted_signal(
    instrumentation: InstrumentationRepository,
    organization_id: str,
    *,
    key: str,
    kind: str,
    quantity: str,
    unit: str,
    pressure_reference: str | None = None,
):
    instrument = instrumentation.create_instrument(
        InstrumentCreate(
            inventory_key=f"{key}-{uuid4().hex}",
            display_name=key,
            instrument_kind=kind,
            pressure_reference=pressure_reference,
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    signal = instrumentation.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"{key}-signal-{uuid4().hex}",
            display_name=f"{key} signal",
            physical_quantity=quantity,
            engineering_unit=unit,
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    instrumentation.append_acceptance(
        instrument.id,
        AcceptanceAppendRequest(
            accepted_for_calculation=True,
            effective_from=T0,
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    return instrument, signal


def test_postgres_circuit_schema_has_org_safe_fks_and_history_guards() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        circuit_fks = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_circuits")
        }
        assert {
            "fk_refrigeration_circuits_organization",
            "fk_refrigeration_circuits_equipment",
        } <= circuit_fks
        binding_fks = {
            item["name"]
            for item in inspector.get_foreign_keys("refrigeration_circuit_signal_bindings")
        }
        assert {
            "fk_refrigeration_circuit_signal_binding_circuit",
            "fk_refrigeration_circuit_signal_binding_signal",
        } <= binding_fks
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                        "AND tgrelid IN ('refrigeration_circuit_lifecycle_history'::regclass, "
                        "'refrigeration_circuit_configuration_history'::regclass, "
                        "'refrigeration_circuit_signal_bindings'::regclass)"
                    )
                ).scalars()
            )
        assert {
            "trg_refrigeration_circuit_lifecycle_guard",
            "trg_refrigeration_circuit_configuration_guard",
            "trg_refrigeration_circuit_signal_binding_guard",
        } <= triggers
    finally:
        engine.dispose()


def test_postgres_binding_handover_preserves_history_and_end_provenance() -> None:
    database, _, repository, instrumentation, organization_id, equipment_id = _scope()
    try:
        circuit, _ = repository.create_circuit(
            CircuitCreateRequest(
                equipment_id=equipment_id,
                business_key=f"circuit-{uuid4().hex}",
                display_name="Handover circuit",
                valid_from=T0,
            ),
            actor_id="operator-a",
            organization_id=organization_id,
        )
        first_instrument, first_signal = _accepted_signal(
            instrumentation,
            organization_id,
            key="TEMP-A",
            kind="temperature_probe",
            quantity="temperature",
            unit="degC",
        )
        _, second_signal = _accepted_signal(
            instrumentation,
            organization_id,
            key="TEMP-B",
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
            organization_id=organization_id,
        )
        with Session(database.engine) as session, session.begin():
            stored_instrument = session.get(type(first_instrument), first_instrument.id)
            stored_signal = session.get(type(first_signal), first_signal.id)
            assert stored_instrument is not None and stored_signal is not None
            stored_instrument.lifecycle_state = "retired"
            stored_signal.lifecycle_state = "retired"

        second = repository.append_binding(
            circuit.id,
            CircuitBindingAppendRequest(
                role="suction_line_temperature",
                signal_id=second_signal.id,
                valid_from=T0 + timedelta(hours=2),
            ),
            actor_id="operator-b",
            organization_id=organization_id,
        )
        history = repository.list_bindings(
            circuit.id,
            include_history=True,
            organization_id=organization_id,
        )
        previous = next(item for item in history if item.binding.id == first.binding.id)
        assert previous.binding.valid_to == second.binding.valid_from
        assert previous.binding.ended_by == "operator-b"
        assert previous.binding.ended_at is not None
        assert repository.resolve_binding(
            circuit.id,
            "suction_line_temperature",
            T0 + timedelta(hours=1, minutes=30),
            organization_id=organization_id,
        ).binding.id == first.binding.id
        assert repository.resolve_binding(
            circuit.id,
            "suction_line_temperature",
            T0 + timedelta(hours=2),
            organization_id=organization_id,
        ).binding.id == second.binding.id
    finally:
        database.dispose()


def test_postgres_direct_sql_guards_fail_closed() -> None:
    database, security, repository, instrumentation, organization_id, equipment_id = _scope()
    other_organization_id = str(uuid4())
    security.provision_organization(
        organization_id=other_organization_id,
        slug=f"rfx06-other-{uuid4().hex}",
        name="RFX06 other organization",
    )
    try:
        circuit, lifecycle = repository.create_circuit(
            CircuitCreateRequest(
                equipment_id=equipment_id,
                business_key=f"guard-{uuid4().hex}",
                display_name="Guard circuit",
                valid_from=T0,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        repository.append_configuration(
            circuit.id,
            CircuitConfigurationAppendRequest(
                refrigerant_code="R404A",
                calculation_policy_version="rfx06-test-v1",
                valid_from=T0,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        _, gauge_signal = _accepted_signal(
            instrumentation,
            organization_id,
            key="GAUGE-ATM",
            kind="pressure_transmitter",
            quantity="pressure",
            unit="bar",
            pressure_reference="gauge",
        )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE refrigeration_circuit_lifecycle_history "
                        "SET state = 'inactive' WHERE id = :id"
                    ),
                    {"id": lifecycle.id},
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuit_lifecycle_history "
                        "(id, organization_id, circuit_id, state, valid_from, valid_to, revision, recorded_by) "
                        "VALUES (:id, :org, :circuit, 'inactive', :start, :finish, 99, 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": organization_id,
                        "circuit": circuit.id,
                        "start": T0 + timedelta(hours=1),
                        "finish": T0 + timedelta(hours=2),
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuit_configuration_history "
                        "(id, organization_id, circuit_id, schema_version, refrigerant_code, "
                        "calculation_policy_version, valid_from, valid_to, revision, recorded_by) "
                        "VALUES (:id, :org, :circuit, 'refrigeration-circuit-configuration/v1', "
                        "'R290', 'direct-test', :start, :finish, 99, 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": organization_id,
                        "circuit": circuit.id,
                        "start": T0 + timedelta(hours=1),
                        "finish": T0 + timedelta(hours=2),
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuit_signal_bindings "
                        "(id, organization_id, circuit_id, signal_id, role, valid_from, revision, recorded_by) "
                        "VALUES (:id, :org, :circuit, :signal, 'atmospheric_pressure', :start, 1, 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": organization_id,
                        "circuit": circuit.id,
                        "signal": gauge_signal.id,
                        "start": T0 + timedelta(hours=1),
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuit_signal_bindings "
                        "(id, organization_id, circuit_id, signal_id, role, valid_from, valid_to, "
                        "revision, recorded_by) "
                        "VALUES (:id, :org, :circuit, :signal, 'suction_pressure', :start, :finish, "
                        "1, 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": organization_id,
                        "circuit": circuit.id,
                        "signal": gauge_signal.id,
                        "start": T0 + timedelta(hours=3),
                        "finish": T0 + timedelta(hours=4),
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuits "
                        "(id, organization_id, equipment_id, business_key, display_name, created_by) "
                        "VALUES (:id, :org, :equipment, :key, 'Guard circuit', 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": organization_id,
                        "equipment": equipment_id,
                        "key": f"duplicate-name-{uuid4().hex}",
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO refrigeration_circuits "
                        "(id, organization_id, equipment_id, business_key, display_name, created_by) "
                        "VALUES (:id, :org, :equipment, :key, 'Cross org', 'direct-sql')"
                    ),
                    {
                        "id": str(uuid4()),
                        "org": other_organization_id,
                        "equipment": equipment_id,
                        "key": f"cross-{uuid4().hex}",
                    },
                )
    finally:
        database.dispose()


def test_postgres_circuit_migration_round_trip() -> None:
    service_root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "20260906_0034"],
        cwd=service_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    downgraded = create_engine(os.environ["DATABASE_URL"])
    try:
        assert not (TABLES & set(inspect(downgraded).get_table_names()))
    finally:
        downgraded.dispose()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=service_root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    upgraded = create_engine(os.environ["DATABASE_URL"])
    try:
        assert TABLES <= set(inspect(upgraded).get_table_names())
        with upgraded.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260908_0037"
    finally:
        upgraded.dispose()
