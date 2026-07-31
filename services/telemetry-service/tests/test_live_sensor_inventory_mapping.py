from __future__ import annotations

from app.climate_catalog.domain import (
    logical_sensor_number,
    temperature_source_channel_id,
)


def test_kk1_physical_sensor_200_routes_to_dixell_126_channel_4() -> None:
    assert logical_sensor_number("KK1", 126, 4) == 200
    assert temperature_source_channel_id(126, 4) == "126-04"
