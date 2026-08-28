from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from app.db import Database
from app.instrumentation.repository import InstrumentationRepository
from app.instrumentation.schemas import (
    AcceptanceAppendRequest,
    InstrumentCreate,
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
