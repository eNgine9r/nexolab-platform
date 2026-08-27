from __future__ import annotations

import pytest

from app.live_dashboard.telemetry_identity import (
    LiveDashboardTelemetryIdentityError,
    telemetry_equipment_id,
)


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
