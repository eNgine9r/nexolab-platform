from __future__ import annotations

from sqlalchemy import String, case, cast, literal

from app.climate_catalog.domain import MeasurementDeviceType
from app.climate_catalog.models import MeasurementDevice


class LiveDashboardTelemetryIdentityError(ValueError):
    pass


def telemetry_equipment_id(*, device_type: str, unit_id: int) -> str:
    if unit_id < 1:
        raise LiveDashboardTelemetryIdentityError(
            f"measurement device unit_id must be positive: {unit_id}"
        )
    if device_type == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value:
        return f"K{unit_id}"
    if device_type == MeasurementDeviceType.ENERGY_METER.value:
        return f"LE01MP-{unit_id}"
    raise LiveDashboardTelemetryIdentityError(
        f"unsupported measurement device type for telemetry identity: {device_type!r}"
    )


def telemetry_equipment_id_expression():
    unit_id_text = cast(MeasurementDevice.unit_id, String)
    return case(
        (
            MeasurementDevice.device_type
            == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value,
            literal("K") + unit_id_text,
        ),
        (
            MeasurementDevice.device_type == MeasurementDeviceType.ENERGY_METER.value,
            literal("LE01MP-") + unit_id_text,
        ),
        else_=None,
    )
