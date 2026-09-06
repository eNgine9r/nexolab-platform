from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier, Thread
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.db import Database
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    AcquisitionSourceAppendRequest,
    AnalogScalingProfileAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.security.repository import SecurityRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for registry constraint validation",
)

REGISTRY_TABLES = {
    "instruments",
    "instrument_signals",
    "instrument_acceptance_history",
    "instrument_calibration_history",
    "instrument_analog_scaling_history",
    "instrument_signal_acquisition_history",
}


def test_migration_created_org_scoped_registry_schema() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        assert REGISTRY_TABLES <= set(inspector.get_table_names())
        signal_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("instrument_signals")
        }
        assert {
            "fk_instrument_signals_organization",
            "fk_instrument_signals_instrument",
        } <= signal_foreign_keys
        instrument_checks = {
            item["name"] for item in inspector.get_check_constraints("instruments")
        }
        assert "ck_instruments_pressure_reference" in instrument_checks
        with engine.connect() as connection:
            trigger_names = set(
                connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE NOT tgisinternal AND tgrelid IN "
                        "('instruments'::regclass, 'instrument_signals'::regclass)"
                    )
                ).scalars()
            )
        assert {
            "trg_instrument_pressure_reference_guard",
            "trg_instrument_signal_pressure_reference_guard",
        } <= trigger_names
        acquisition_foreign_keys = {
            item["name"]
            for item in inspector.get_foreign_keys(
                "instrument_signal_acquisition_history"
            )
        }
        assert {
            "fk_instrument_signal_acquisition_organization",
            "fk_instrument_signal_acquisition_signal",
        } <= acquisition_foreign_keys
        with engine.connect() as connection:
            acquisition_triggers = set(
                connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                        "AND tgrelid = 'instrument_signal_acquisition_history'::regclass"
                    )
                ).scalars()
            )
        assert "trg_instrument_signal_acquisition_history_guard" in acquisition_triggers
        acceptance_checks = {
            item["name"]
            for item in inspector.get_check_constraints(
                "instrument_acceptance_history"
            )
        }
        assert {
            "ck_instrument_acceptance_schema_version",
            "ck_instrument_acceptance_interval",
            "ck_instrument_acceptance_revision_positive",
        } <= acceptance_checks
        calibration_checks = {
            item["name"]
            for item in inspector.get_check_constraints(
                "instrument_calibration_history"
            )
        }
        assert {
            "ck_instrument_calibration_schema_version",
            "ck_instrument_calibration_state",
            "ck_instrument_calibration_interval",
        } <= calibration_checks
    finally:
        engine.dispose()


def test_postgres_prevents_cross_org_links_overlap_and_history_rewrite() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    other_organization_id = str(uuid4())
    suffix = uuid4().hex
    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"instrumentation-{suffix}",
            name="Instrumentation test organization",
        )
        security.provision_organization(
            organization_id=other_organization_id,
            slug=f"instrumentation-other-{suffix}",
            name="Other instrumentation test organization",
        )
        instrument = repository.create_instrument(
            InstrumentCreate(
                inventory_key=f"PG-{suffix}",
                display_name="PostgreSQL registry probe",
                instrument_kind="temperature_probe",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO instrument_signals (
                            id, organization_id, instrument_id, business_key,
                            display_name, physical_quantity, engineering_unit,
                            lifecycle_state, metadata, version, created_by,
                            updated_by, created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :instrument_id, :business_key,
                            'cross organization', 'temperature', 'degC',
                            'active', '{}'::json, 1, 'test-suite', 'test-suite',
                            now(), now()
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "organization_id": other_organization_id,
                        "instrument_id": instrument.id,
                        "business_key": f"CROSS-{suffix}",
                    },
                )

        start = datetime(2026, 8, 1, tzinfo=UTC)
        first = repository.append_acceptance(
            instrument.id,
            AcceptanceAppendRequest(
                accepted_for_calculation=True,
                effective_from=start,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        repository.append_acceptance(
            instrument.id,
            AcceptanceAppendRequest(
                accepted_for_calculation=False,
                effective_from=start + timedelta(days=2),
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO instrument_acceptance_history (
                            id, organization_id, instrument_id, schema_version,
                            accepted_for_calculation, state_label,
                            effective_from, effective_to, revision,
                            recorded_by, recorded_at
                        ) VALUES (
                            :id, :organization_id, :instrument_id,
                            'acceptance-state/v1', true, 'overlap',
                            :effective_from, :effective_to, 99,
                            'test-suite', now()
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "organization_id": organization_id,
                        "instrument_id": instrument.id,
                        "effective_from": start + timedelta(days=1),
                        "effective_to": start + timedelta(days=3),
                    },
                )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE instrument_acceptance_history "
                        "SET accepted_for_calculation = false WHERE id = :id"
                    ),
                    {"id": first.id},
                )
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM instrument_acceptance_history WHERE id = :id"),
                    {"id": first.id},
                )
    finally:
        database.dispose()


def test_postgres_pressure_signal_reference_guards_fail_closed() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    suffix = uuid4().hex
    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"instrumentation-pressure-{suffix}",
            name="Pressure reference guard organization",
        )
        instrument = repository.create_instrument(
            InstrumentCreate(
                inventory_key=f"PRESS-{suffix}",
                display_name="Pressure reference guard probe",
                instrument_kind="pressure_transmitter",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        signal_id = str(uuid4())
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO instrument_signals (
                            id, organization_id, instrument_id, business_key,
                            display_name, physical_quantity, engineering_unit,
                            lifecycle_state, metadata, version, created_by, updated_by,
                            created_at, updated_at
                        ) VALUES (
                            :id, :organization_id, :instrument_id, :business_key,
                            'Pressure', 'pressure', 'bar', 'active', '{}'::json, 1,
                            'test-suite', 'test-suite', now(), now()
                        )
                        """
                    ),
                    {
                        "id": signal_id,
                        "organization_id": organization_id,
                        "instrument_id": instrument.id,
                        "business_key": f"PRESS-{suffix}.PRIMARY",
                    },
                )

        with database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE instruments SET pressure_reference = 'gauge' "
                    "WHERE organization_id = :organization_id AND id = :instrument_id"
                ),
                {"organization_id": organization_id, "instrument_id": instrument.id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO instrument_signals (
                        id, organization_id, instrument_id, business_key,
                        display_name, physical_quantity, engineering_unit,
                        lifecycle_state, metadata, version, created_by, updated_by,
                        created_at, updated_at
                    ) VALUES (
                        :id, :organization_id, :instrument_id, :business_key,
                        'Pressure', 'pressure', 'bar', 'active', '{}'::json, 1,
                        'test-suite', 'test-suite', now(), now()
                    )
                    """
                ),
                {
                    "id": signal_id,
                    "organization_id": organization_id,
                    "instrument_id": instrument.id,
                    "business_key": f"PRESS-{suffix}.PRIMARY",
                },
            )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE instruments SET pressure_reference = NULL "
                        "WHERE organization_id = :organization_id AND id = :instrument_id"
                    ),
                    {"organization_id": organization_id, "instrument_id": instrument.id},
                )
    finally:
        database.dispose()


def test_postgres_guards_stable_registry_identity_against_direct_sql() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    suffix = uuid4().hex
    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"instrumentation-stable-{suffix}",
            name="Stable instrumentation organization",
        )
        instrument = repository.create_instrument(
            InstrumentCreate(
                inventory_key=f"STABLE-{suffix}",
                display_name="Stable pressure instrument",
                instrument_kind="pressure_transmitter",
                pressure_reference="gauge",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        signal = repository.create_signal(
            instrument.id,
            SignalCreate(
                business_key=f"STABLE-{suffix}.PRESSURE",
                display_name="Pressure",
                physical_quantity="pressure",
                engineering_unit="bar",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )

        with database.engine.begin() as connection:
            connection.execute(
                text("UPDATE instruments SET display_name = 'Mutable label' WHERE id = :id"),
                {"id": instrument.id},
            )
            connection.execute(
                text("UPDATE instrument_signals SET display_name = 'Mutable signal' WHERE id = :id"),
                {"id": signal.id},
            )

        for statement in (
            "UPDATE instruments SET inventory_key = inventory_key || '-X' WHERE id = :id",
            "UPDATE instruments SET instrument_kind = 'humidity_transmitter' WHERE id = :id",
            "UPDATE instruments SET pressure_reference = 'absolute' WHERE id = :id",
        ):
            with pytest.raises(DBAPIError):
                with database.engine.begin() as connection:
                    connection.execute(text(statement), {"id": instrument.id})

        for statement in (
            "UPDATE instrument_signals SET business_key = business_key || '-X' WHERE id = :id",
            "UPDATE instrument_signals SET physical_quantity = 'humidity' WHERE id = :id",
            "UPDATE instrument_signals SET engineering_unit = 'Pa' WHERE id = :id",
        ):
            with pytest.raises(DBAPIError):
                with database.engine.begin() as connection:
                    connection.execute(text(statement), {"id": signal.id})
    finally:
        database.dispose()


@pytest.mark.parametrize("history_kind", ["acceptance", "calibration"])
def test_postgres_serializes_concurrent_history_overlap(history_kind: str) -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    suffix = uuid4().hex
    security.provision_organization(
        organization_id=organization_id,
        slug=f"instrumentation-race-{suffix}",
        name="Instrumentation concurrency test organization",
    )
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key=f"RACE-{suffix}",
            display_name="Concurrent history probe",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    start = datetime(2026, 8, 1, tzinfo=UTC)
    ready = Barrier(2)
    outcomes: list[str] = []

    if history_kind == "acceptance":
        statement = text(
            """
            INSERT INTO instrument_acceptance_history (
                id, organization_id, instrument_id, schema_version,
                accepted_for_calculation, state_label,
                effective_from, effective_to, revision,
                recorded_by, recorded_at
            ) VALUES (
                :id, :organization_id, :instrument_id,
                'acceptance-state/v1', true, 'concurrency-test',
                :interval_from, :interval_to, :revision,
                'test-suite', now()
            )
            """
        )
    else:
        statement = text(
            """
            INSERT INTO instrument_calibration_history (
                id, organization_id, instrument_id, calibration_scope,
                schema_version, state, certificate_reference,
                valid_from, valid_to, revision, recorded_by, recorded_at
            ) VALUES (
                :id, :organization_id, :instrument_id, 'default',
                'calibration-state/v1', 'valid', NULL,
                :interval_from, :interval_to, :revision,
                'test-suite', now()
            )
            """
        )

    def insert_interval(offset_hours: int, revision: int) -> None:
        try:
            with database.engine.begin() as connection:
                ready.wait(timeout=5)
                connection.execute(
                    statement,
                    {
                        "id": str(uuid4()),
                        "organization_id": organization_id,
                        "instrument_id": instrument.id,
                        "interval_from": start + timedelta(hours=offset_hours),
                        "interval_to": start + timedelta(days=2),
                        "revision": revision,
                    },
                )
            outcomes.append("committed")
        except DBAPIError:
            outcomes.append("rejected")

    first = Thread(target=insert_interval, args=(0, 100), daemon=True)
    second = Thread(target=insert_interval, args=(1, 101), daemon=True)
    first.start()
    second.start()
    first.join(timeout=10)
    second.join(timeout=10)

    try:
        assert not first.is_alive()
        assert not second.is_alive()
        assert sorted(outcomes) == ["committed", "rejected"]
    finally:
        database.dispose()


def test_postgres_analog_scaling_history_guards_fail_closed() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    other_organization_id = str(uuid4())
    suffix = uuid4().hex
    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"analog-scaling-{suffix}",
            name="Analog scaling PostgreSQL organization",
        )
        security.provision_organization(
            organization_id=other_organization_id,
            slug=f"analog-scaling-other-{suffix}",
            name="Other analog scaling organization",
        )
        instrument = repository.create_instrument(
            InstrumentCreate(
                inventory_key=f"ANALOG-{suffix}",
                display_name="Analog pressure transmitter",
                instrument_kind="pressure_transmitter",
                pressure_reference="gauge",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        signal = repository.create_signal(
            instrument.id,
            SignalCreate(
                business_key=f"ANALOG-{suffix}.PRESSURE",
                display_name="Pressure",
                physical_quantity="pressure",
                engineering_unit="bar",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        start = datetime(2026, 9, 6, tzinfo=UTC)
        profile = repository.append_analog_scaling_profile(
            instrument.id,
            signal.id,
            AnalogScalingProfileAppendRequest(
                raw_unit="mA",
                raw_min="4",
                raw_max="20",
                engineering_min="0",
                engineering_max="30",
                engineering_unit="bar",
                evidence_status="hardware_unverified",
                effective_from=start,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE instrument_analog_scaling_history "
                        "SET engineering_max = 40 WHERE id = :id"
                    ),
                    {"id": profile.id},
                )
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM instrument_analog_scaling_history WHERE id = :id"),
                    {"id": profile.id},
                )

        def direct_insert(*, row_id: str, org_id: str, unit: str, evidence_status: str,
                          interval_from: datetime, interval_to: datetime | None, revision: int,
                          provenance: bool = False) -> None:
            values = {
                "id": row_id,
                "organization_id": org_id,
                "signal_id": signal.id,
                "engineering_unit": unit,
                "evidence_status": evidence_status,
                "effective_from": interval_from,
                "effective_to": interval_to,
                "revision": revision,
                "device_family": "xjp60d" if provenance else None,
                "profile_id": "evidence-profile" if provenance else None,
                "profile_version": "v1" if provenance else None,
                "channel_reference": "channel-1" if provenance else None,
            }
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO instrument_analog_scaling_history (
                            id, organization_id, signal_id, schema_version,
                            electrical_input_class, raw_unit, raw_min, raw_max,
                            engineering_min, engineering_max, engineering_unit,
                            scaling_policy, under_range_policy, over_range_policy,
                            acquisition_device_family, acquisition_profile_id,
                            acquisition_profile_version, acquisition_channel_reference,
                            calibration_scope, evidence_status, effective_from, effective_to,
                            revision, recorded_by, recorded_at
                        ) VALUES (
                            :id, :organization_id, :signal_id, 'analog-scaling/v1',
                            'current_loop_4_20ma', 'mA', 4, 20, 0, 30, :engineering_unit,
                            'linear_two_point', 'unavailable', 'unavailable',
                            :device_family, :profile_id, :profile_version, :channel_reference,
                            'instrument', :evidence_status, :effective_from, :effective_to,
                            :revision, 'test-suite', now()
                        )
                        """
                    ),
                    values,
                )

        with pytest.raises(DBAPIError):
            direct_insert(
                row_id=str(uuid4()),
                org_id=organization_id,
                unit="kPa",
                evidence_status="hardware_unverified",
                interval_from=start + timedelta(days=2),
                interval_to=start + timedelta(days=3),
                revision=90,
            )
        with pytest.raises(DBAPIError):
            direct_insert(
                row_id=str(uuid4()),
                org_id=organization_id,
                unit="bar",
                evidence_status="hardware_verified",
                interval_from=start + timedelta(days=2),
                interval_to=start + timedelta(days=3),
                revision=91,
            )
        with pytest.raises(DBAPIError):
            direct_insert(
                row_id=str(uuid4()),
                org_id=other_organization_id,
                unit="bar",
                evidence_status="hardware_unverified",
                interval_from=start + timedelta(days=2),
                interval_to=start + timedelta(days=3),
                revision=92,
            )
        with pytest.raises(DBAPIError):
            direct_insert(
                row_id=str(uuid4()),
                org_id=organization_id,
                unit="bar",
                evidence_status="hardware_unverified",
                interval_from=start + timedelta(hours=1),
                interval_to=start + timedelta(days=1),
                revision=93,
            )
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO instrument_analog_scaling_history (
                            id, organization_id, signal_id, schema_version,
                            electrical_input_class, raw_unit, raw_min, raw_max,
                            engineering_min, engineering_max, engineering_unit,
                            scaling_policy, under_range_policy, over_range_policy,
                            calibration_scope, evidence_status, effective_from, effective_to,
                            revision, recorded_by, recorded_at
                        ) VALUES (
                            :id, :organization_id, :signal_id, 'analog-scaling/v1',
                            'current_loop_4_20ma', 'count', 0, 'Infinity'::numeric,
                            0, 30, 'bar', 'linear_two_point', 'unavailable', 'unavailable',
                            'instrument', 'hardware_unverified', :effective_from, :effective_to,
                            94, 'test-suite', now()
                        )
                        """
                    ),
                    {
                        "id": str(uuid4()),
                        "organization_id": organization_id,
                        "signal_id": signal.id,
                        "effective_from": start + timedelta(days=4),
                        "effective_to": start + timedelta(days=5),
                    },
                )
    finally:
        database.dispose()


def test_postgres_analog_scaling_preserves_numeric_38_18_precision() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    suffix = uuid4().hex
    exact_min = Decimal("-99999999999999999999.123456789012345678")
    exact_max = Decimal("99999999999999999999.123456789012345678")
    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"analog-precision-{suffix}",
            name="Analog precision PostgreSQL organization",
        )
        instrument = repository.create_instrument(
            InstrumentCreate(
                inventory_key=f"ANALOG-PRECISION-{suffix}",
                display_name="Precision pressure transmitter",
                instrument_kind="pressure_transmitter",
                pressure_reference="gauge",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        signal = repository.create_signal(
            instrument.id,
            SignalCreate(
                business_key=f"ANALOG-PRECISION-{suffix}.PRESSURE",
                display_name="Pressure",
                physical_quantity="pressure",
                engineering_unit="bar",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        start = datetime(2026, 9, 6, tzinfo=UTC)
        created = repository.append_analog_scaling_profile(
            instrument.id,
            signal.id,
            AnalogScalingProfileAppendRequest(
                raw_unit="mA",
                raw_min="4.123456789012345678",
                raw_max="20",
                engineering_min=exact_min,
                engineering_max=exact_max,
                engineering_unit="bar",
                evidence_status="hardware_unverified",
                effective_from=start,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        history = repository.list_analog_scaling_history(
            instrument.id, signal.id, organization_id=organization_id
        )
        resolved = repository.resolve_analog_scaling_profile(
            instrument.id, signal.id, start, organization_id=organization_id
        )

        assert created.engineering_min == exact_min
        assert created.engineering_max == exact_max
        assert history[0].engineering_min == exact_min
        assert history[0].engineering_max == exact_max
        assert resolved.engineering_min == exact_min
        assert resolved.engineering_max == exact_max
    finally:
        database.dispose()


def test_postgres_analog_scaling_schema_has_expected_fk_checks_and_trigger() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        foreign_keys = {
            item["name"]
            for item in inspector.get_foreign_keys("instrument_analog_scaling_history")
        }
        assert {
            "fk_instrument_analog_scaling_organization",
            "fk_instrument_analog_scaling_signal",
        } <= foreign_keys
        checks = {
            item["name"]
            for item in inspector.get_check_constraints("instrument_analog_scaling_history")
        }
        assert {
            "ck_instrument_analog_scaling_schema_version",
            "ck_instrument_analog_scaling_input_class",
            "ck_instrument_analog_scaling_policy",
            "ck_instrument_analog_scaling_raw_domain",
            "ck_instrument_analog_scaling_finite_values",
            "ck_instrument_analog_scaling_hardware_provenance",
        } <= checks
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal "
                        "AND tgrelid = 'instrument_analog_scaling_history'::regclass"
                    )
                ).scalars()
            )
        assert "trg_instrument_analog_scaling_history_guard" in triggers
    finally:
        engine.dispose()


def test_postgres_acquisition_source_guards_unit_overlap_and_immutability() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    other_organization_id = str(uuid4())
    suffix = uuid4().hex
    security.provision_organization(
        organization_id=organization_id,
        slug=f"humidity-source-{suffix}",
        name="Humidity source PostgreSQL guard",
    )
    security.provision_organization(
        organization_id=other_organization_id,
        slug=f"humidity-source-other-{suffix}",
        name="Other humidity source organization",
    )
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key=f"RH-{suffix}",
            display_name="Humidity transmitter",
            instrument_kind="humidity_transmitter",
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"RH-{suffix}.PRIMARY",
            display_name="Relative humidity",
            physical_quantity="relative_humidity",
            engineering_unit="%RH",
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    start = datetime(2026, 9, 6, tzinfo=UTC)
    source = repository.append_acquisition_source(
        instrument.id,
        signal.id,
        AcquisitionSourceAppendRequest(
            node_id="edge-01",
            equipment_id="humidity-01",
            channel_id="ai-1",
            metric="humidity.relative",
            unit="%RH",
            evidence_status="hardware_unverified",
            valid_from=start,
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )

    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE instrument_signal_acquisition_history SET metric = 'guessed' "
                "WHERE id = :id"
            ),
            {"id": source.id},
        )
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO instrument_analog_scaling_history (
                    id, organization_id, signal_id, schema_version,
                    electrical_input_class, raw_unit, raw_min, raw_max,
                    engineering_min, engineering_max, engineering_unit,
                    scaling_policy, under_range_policy, over_range_policy,
                    acquisition_source_id, calibration_scope, evidence_status,
                    effective_from, effective_to, revision, recorded_by, recorded_at
                ) VALUES (
                    :id, :organization_id, :signal_id, 'analog-scaling/v1',
                    'current_loop_4_20ma', 'mA', 4, 20, 10, 90, '%RH',
                    'linear_two_point', 'unavailable', 'unavailable',
                    :acquisition_source_id, 'instrument', 'hardware_unverified',
                    :effective_from, NULL, 99, 'test-suite', now()
                )
                """
            ),
            {
                "id": str(uuid4()),
                "organization_id": organization_id,
                "signal_id": signal.id,
                "acquisition_source_id": str(uuid4()),
                "effective_from": start,
            },
        )
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO instrument_signal_acquisition_history (
                    id, organization_id, signal_id, schema_version, node_id,
                    equipment_id, channel_id, metric, unit, evidence_status,
                    valid_from, valid_to, revision, recorded_by, recorded_at
                ) VALUES (
                    :id, :organization_id, :signal_id, 'acquisition-source/v1',
                    'edge-other', 'humidity-other', 'ai-1', 'humidity.relative',
                    '%RH', 'hardware_unverified', :valid_from, NULL, 1,
                    'test-suite', now()
                )
                """
            ),
            {
                "id": str(uuid4()),
                "organization_id": other_organization_id,
                "signal_id": signal.id,
                "valid_from": start,
            },
        )
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO instrument_signal_acquisition_history (
                    id, organization_id, signal_id, schema_version, node_id,
                    equipment_id, channel_id, metric, unit, evidence_status,
                    valid_from, valid_to, revision, recorded_by, recorded_at
                ) VALUES (
                    :id, :organization_id, :signal_id, 'acquisition-source/v1',
                    'edge-02', 'humidity-02', 'ai-2', 'humidity.relative',
                    :unit, 'hardware_unverified', :valid_from, NULL, 2,
                    'test-suite', now()
                )
                """
            ),
            {
                "id": str(uuid4()),
                "organization_id": organization_id,
                "signal_id": signal.id,
                "unit": "degC",
                "valid_from": start + timedelta(hours=1),
            },
        )
    with pytest.raises(DBAPIError), database.engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO instrument_signal_acquisition_history (
                    id, organization_id, signal_id, schema_version, node_id,
                    equipment_id, channel_id, metric, unit, evidence_status,
                    valid_from, valid_to, revision, recorded_by, recorded_at
                ) VALUES (
                    :id, :organization_id, :signal_id, 'acquisition-source/v1',
                    'edge-02', 'humidity-02', 'ai-2', 'humidity.relative',
                    '%RH', 'hardware_unverified', :valid_from, NULL, 3,
                    'test-suite', now()
                )
                """
            ),
            {
                "id": str(uuid4()),
                "organization_id": organization_id,
                "signal_id": signal.id,
                "valid_from": start + timedelta(hours=1),
            },
        )
    database.dispose()


def test_postgres_rfx03_migration_roundtrip_preserves_rfx01_rfx02_sentinels() -> None:
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    repository = InstrumentationRepository(database)
    organization_id = str(uuid4())
    suffix = uuid4().hex
    security.provision_organization(
        organization_id=organization_id,
        slug=f"rfx03-roundtrip-{suffix}",
        name="RFX-03 migration round-trip",
    )
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key=f"RFX03-{suffix}",
            display_name="RFX-03 round-trip instrument",
            instrument_kind="humidity_transmitter",
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    signal = repository.create_signal(
        instrument.id,
        SignalCreate(
            business_key=f"RFX03-{suffix}.RH",
            display_name="RFX-03 round-trip signal",
            physical_quantity="relative_humidity",
            engineering_unit="%RH",
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    profile = repository.append_analog_scaling_profile(
        instrument.id,
        signal.id,
        AnalogScalingProfileAppendRequest(
            raw_unit="mA",
            raw_min="4",
            raw_max="20",
            engineering_min="10",
            engineering_max="90",
            engineering_unit="%RH",
            evidence_status="hardware_unverified",
            effective_from=datetime(2026, 9, 6, tzinfo=UTC),
        ),
        actor_id="test-suite",
        organization_id=organization_id,
    )
    database.dispose()

    def run_alembic(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            check=True,
            env=os.environ.copy(),
        )

    run_alembic("downgrade", "20260906_0033")
    try:
        downgraded = create_engine(os.environ["DATABASE_URL"])
        try:
            with downgraded.connect() as connection:
                assert connection.scalar(
                    text("SELECT count(*) FROM instrument_signals WHERE id = :id"),
                    {"id": signal.id},
                ) == 1
                assert connection.scalar(
                    text(
                        "SELECT count(*) FROM instrument_analog_scaling_history WHERE id = :id"
                    ),
                    {"id": profile.id},
                ) == 1
            downgraded_inspector = inspect(downgraded)
            assert "instrument_signal_acquisition_history" not in set(
                downgraded_inspector.get_table_names()
            )
            assert "acquisition_source_id" not in {
                column["name"]
                for column in downgraded_inspector.get_columns(
                    "instrument_analog_scaling_history"
                )
            }
        finally:
            downgraded.dispose()
    finally:
        run_alembic("upgrade", "head")

    upgraded = create_engine(os.environ["DATABASE_URL"])
    try:
        upgraded_inspector = inspect(upgraded)
        assert "instrument_signal_acquisition_history" in set(
            upgraded_inspector.get_table_names()
        )
        assert "acquisition_source_id" in {
            column["name"]
            for column in upgraded_inspector.get_columns(
                "instrument_analog_scaling_history"
            )
        }
        with upgraded.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM instrument_signals WHERE id = :id"),
                {"id": signal.id},
            ) == 1
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM instrument_analog_scaling_history WHERE id = :id"
                ),
                {"id": profile.id},
            ) == 1
    finally:
        upgraded.dispose()
