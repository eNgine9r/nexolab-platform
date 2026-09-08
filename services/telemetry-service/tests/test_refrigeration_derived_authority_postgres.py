from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.db import Database
from app.instrumentation.profile_acceptance import (
    AcquisitionProfileAcceptanceRepository,
    ProfileAcceptanceAppendRequest,
)
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcquisitionSourceAppendRequest,
    InstrumentCreate,
    SignalCreate,
)
from app.refrigeration.calculation_policy import (
    CalculationPolicyCreateRequest,
    CalculationPolicyRepository,
)
from app.security.repository import SecurityRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for thermodynamics authority validation",
)


def _repositories():
    database = Database(os.environ["DATABASE_URL"])
    security = SecurityRepository(database)
    organization_id = str(uuid4())
    security.provision_organization(
        organization_id=organization_id,
        slug=f"rfx08b-{uuid4().hex}",
        name="RFX-08B PostgreSQL organization",
    )
    return (
        database,
        security,
        InstrumentationRepository(database),
        AcquisitionProfileAcceptanceRepository(database),
        CalculationPolicyRepository(database),
        organization_id,
    )


def test_migration_created_authority_schema_and_guards() -> None:
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "refrigeration_calculation_policies",
            "instrument_acquisition_profile_acceptance_history",
        } <= tables
        source_columns = {
            item["name"]
            for item in inspector.get_columns("instrument_signal_acquisition_history")
        }
        assert {
            "acquisition_profile_id",
            "acquisition_profile_version",
            "calibration_scope",
        } <= source_columns
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
        assert {
            "trg_refrigeration_calculation_policy_guard",
            "trg_instrument_acquisition_profile_acceptance_history_guard",
        } <= triggers
    finally:
        engine.dispose()


def test_policy_is_immutable_and_database_rejects_unsupported_states() -> None:
    database, _, _, _, policies, organization_id = _repositories()
    try:
        policy = policies.create(
            CalculationPolicyCreateRequest(
                version=f"policy-{uuid4().hex}",
                maximum_age_ms=10_000,
                maximum_future_clock_skew_ms=0,
                maximum_cross_input_skew_ms=1_000,
                accepted_calibration_states=["valid"],
                require_calibration_at_observation=False,
                calibration_required_roles=[],
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        with pytest.raises(DBAPIError), database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE refrigeration_calculation_policies "
                    "SET maximum_age_ms = 999 WHERE id = :id"
                ),
                {"id": policy.id},
            )
        with pytest.raises(DBAPIError), database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM refrigeration_calculation_policies WHERE id = :id"),
                {"id": policy.id},
            )
        with pytest.raises(DBAPIError), database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO refrigeration_calculation_policies "
                    "(id, organization_id, schema_version, version, maximum_age_ms, "
                    "maximum_future_clock_skew_ms, maximum_cross_input_skew_ms, "
                    "calibration_vocabulary_version, accepted_calibration_states, "
                    "require_calibration_at_observation, calibration_required_roles, created_by) "
                    "VALUES (:id, :org, 'refrigeration-calculation-policy/v1', :version, "
                    "1000, 0, 100, 'calibration-state/v1', CAST('[\"expired\"]' AS JSON), "
                    "false, CAST('[]' AS JSON), 'test-suite')"
                ),
                {"id": str(uuid4()), "org": organization_id, "version": uuid4().hex},
            )
    finally:
        database.dispose()


def test_profile_acceptance_guard_preserves_exact_source_identity_and_half_open_handover() -> (
    None
):
    database, _, instrumentation, profiles, _, organization_id = _repositories()
    start = datetime.now(UTC).replace(microsecond=0)
    try:
        instrument = instrumentation.create_instrument(
            InstrumentCreate(
                inventory_key=f"INST-{uuid4().hex}",
                display_name="Digital temperature probe",
                instrument_kind="temperature_probe",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        signal = instrumentation.create_signal(
            instrument.id,
            SignalCreate(
                business_key=f"SIG-{uuid4().hex}",
                display_name="Temperature",
                physical_quantity="temperature",
                engineering_unit="degC",
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        source = instrumentation.append_acquisition_source(
            instrument.id,
            signal.id,
            AcquisitionSourceAppendRequest(
                node_id="edge-01",
                equipment_id="equipment-01",
                channel_id="modbus-1",
                metric="temperature",
                unit="degC",
                acquisition_profile_id="xjp60d-temperature",
                acquisition_profile_version="1",
                valid_from=start,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        first = profiles.append(
            instrument.id,
            signal.id,
            source.id,
            ProfileAcceptanceAppendRequest(
                accepted_for_calculation=True,
                effective_from=start,
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        second = profiles.append(
            instrument.id,
            signal.id,
            source.id,
            ProfileAcceptanceAppendRequest(
                accepted_for_calculation=False,
                effective_from=start + timedelta(seconds=10),
            ),
            actor_id="test-suite",
            organization_id=organization_id,
        )
        assert (
            profiles.resolve(
                instrument.id,
                signal.id,
                source.id,
                start + timedelta(seconds=9),
                organization_id=organization_id,
            ).id
            == first.id
        )
        assert (
            profiles.resolve(
                instrument.id,
                signal.id,
                source.id,
                second.effective_from,
                organization_id=organization_id,
            ).id
            == second.id
        )

        with pytest.raises(DBAPIError), database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE instrument_acquisition_profile_acceptance_history "
                    "SET accepted_for_calculation = true WHERE id = :id"
                ),
                {"id": second.id},
            )
        with pytest.raises(DBAPIError), database.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO instrument_acquisition_profile_acceptance_history "
                    "(id, organization_id, signal_id, acquisition_source_id, scaling_profile_id, "
                    "profile_target_key, schema_version, acquisition_profile_id, "
                    "acquisition_profile_version, accepted_for_calculation, effective_from, "
                    "revision, recorded_by) VALUES "
                    "(:id, :org, :signal, :source, NULL, :target, 'acceptance-state/v1', "
                    "'wrong-profile', '1', true, :at, 99, 'test-suite')"
                ),
                {
                    "id": str(uuid4()),
                    "org": organization_id,
                    "signal": signal.id,
                    "source": source.id,
                    "target": f"source:{source.id}",
                    "at": start + timedelta(hours=1),
                },
            )
    finally:
        database.dispose()


def test_authority_migration_downgrade_upgrade_roundtrip() -> None:
    service_root = os.path.dirname(os.path.dirname(__file__))

    def alembic(*args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=service_root,
            env=os.environ.copy(),
            check=True,
            capture_output=True,
            text=True,
        )

    alembic("downgrade", "20260906_0035")
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        assert "refrigeration_calculation_policies" not in inspector.get_table_names()
        columns = {
            item["name"]
            for item in inspector.get_columns("instrument_signal_acquisition_history")
        }
        assert "acquisition_profile_id" not in columns
    finally:
        engine.dispose()
        alembic("upgrade", "head")

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        inspector = inspect(engine)
        assert "refrigeration_calculation_policies" in inspector.get_table_names()
        columns = {
            item["name"]
            for item in inspector.get_columns("instrument_signal_acquisition_history")
        }
        assert "acquisition_profile_id" in columns
    finally:
        engine.dispose()
