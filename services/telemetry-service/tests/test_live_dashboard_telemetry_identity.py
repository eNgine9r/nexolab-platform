from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.climate_catalog.models import MeasurementDevice
from app.live_dashboard.telemetry_identity import (
    LiveDashboardTelemetryIdentityError,
    telemetry_equipment_id,
    telemetry_equipment_id_expression,
)
from tests.live_dashboard_test_support import ORG_A, database_with_inventory


def test_temperature_controller_uses_device_agent_equipment_identity() -> None:
    assert telemetry_equipment_id(device_type="temperature_controller", unit_id=108) == "K108"


def test_energy_meter_preserves_device_agent_equipment_identity() -> None:
    assert telemetry_equipment_id(device_type="energy_meter", unit_id=200) == "LE01MP-200"


@pytest.mark.parametrize(
    ("device_type", "unit_id"),
    [("future_device", 108), ("temperature_controller", 0)],
)
def test_unknown_or_invalid_catalog_identity_fails_closed(
    device_type: str,
    unit_id: int,
) -> None:
    with pytest.raises(LiveDashboardTelemetryIdentityError):
        telemetry_equipment_id(device_type=device_type, unit_id=unit_id)


def test_energy_meter_sql_identity_expression_matches_device_agent_contract(tmp_path) -> None:
    database, _ = database_with_inventory(tmp_path)
    with Session(database.engine) as session:
        with session.begin():
            session.execute(
                update(MeasurementDevice)
                .where(MeasurementDevice.organization_id == ORG_A)
                .values(
                    business_key="LE01MP-200",
                    device_type="energy_meter",
                    unit_id=200,
                )
            )
        resolved = session.scalar(
            select(telemetry_equipment_id_expression())
            .select_from(MeasurementDevice)
            .where(MeasurementDevice.organization_id == ORG_A)
            .limit(1)
        )
    assert resolved == "LE01MP-200"
