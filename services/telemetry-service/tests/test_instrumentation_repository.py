from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.instrumentation.models import InstrumentAcceptanceRecord
from app.instrumentation.repository import (
    HistoryResolutionError,
    InstrumentationRepository,
)
from app.instrumentation.schemas import InstrumentCreate
from app.model_registry import register_models
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def build_repository(tmp_path: Path) -> tuple[Database, InstrumentationRepository, str]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'instrumentation-repository.db'}")
    database.create_schema()
    SecurityRepository(database).provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository = InstrumentationRepository(database)
    instrument = repository.create_instrument(
        InstrumentCreate(
            inventory_key="RESOLUTION-001",
            display_name="Resolution test instrument",
            instrument_kind="temperature_probe",
        ),
        actor_id="test-suite",
        organization_id=ORGANIZATION_ID,
    )
    return database, repository, instrument.id


def test_as_of_resolution_fails_closed_when_no_state_exists(tmp_path: Path) -> None:
    _, repository, instrument_id = build_repository(tmp_path)

    with pytest.raises(HistoryResolutionError, match="exactly one"):
        repository.resolve_acceptance(
            instrument_id,
            datetime(2026, 8, 28, tzinfo=UTC),
            organization_id=ORGANIZATION_ID,
        )
    with pytest.raises(HistoryResolutionError, match="exactly one"):
        repository.resolve_calibration(
            instrument_id,
            datetime(2026, 8, 28, tzinfo=UTC),
            organization_id=ORGANIZATION_ID,
        )


def test_as_of_resolution_fails_closed_for_ambiguous_imported_intervals(
    tmp_path: Path,
) -> None:
    database, repository, instrument_id = build_repository(tmp_path)
    start = datetime(2026, 8, 1, tzinfo=UTC)
    end = start + timedelta(days=10)
    recorded = datetime(2026, 8, 28, tzinfo=UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add_all(
                [
                    InstrumentAcceptanceRecord(
                        id=str(uuid4()),
                        organization_id=ORGANIZATION_ID,
                        instrument_id=instrument_id,
                        schema_version="acceptance-state/v1",
                        accepted_for_calculation=True,
                        state_label="import-a",
                        effective_from=start,
                        effective_to=end,
                        revision=1,
                        recorded_by="importer",
                        recorded_at=recorded,
                    ),
                    InstrumentAcceptanceRecord(
                        id=str(uuid4()),
                        organization_id=ORGANIZATION_ID,
                        instrument_id=instrument_id,
                        schema_version="acceptance-state/v1",
                        accepted_for_calculation=False,
                        state_label="import-b",
                        effective_from=start + timedelta(days=1),
                        effective_to=end,
                        revision=2,
                        recorded_by="importer",
                        recorded_at=recorded,
                    ),
                ]
            )

    with pytest.raises(HistoryResolutionError, match="exactly one"):
        repository.resolve_acceptance(
            instrument_id,
            start + timedelta(days=2),
            organization_id=ORGANIZATION_ID,
        )
