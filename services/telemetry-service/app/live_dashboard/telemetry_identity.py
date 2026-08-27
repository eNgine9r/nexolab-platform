from __future__ import annotations

from sqlalchemy import String, and_, case, cast, literal

from app.climate_catalog.domain import MeasurementDeviceType
from app.climate_catalog.models import MeasurementDevice


MAX_MODBUS_UNIT_ID = 247


class LiveDashboardTelemetryIdentityError(ValueError):
    pass


def telemetry_equipment_id(*, device_type: str, unit_id: int) -> str:
    if not 1 <= unit_id <= MAX_MODBUS_UNIT_ID:
        raise LiveDashboardTelemetryIdentityError(
            f"measurement device unit_id must be 1..{MAX_MODBUS_UNIT_ID}: {unit_id}"
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
            and_(
                MeasurementDevice.device_type
                == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value,
                MeasurementDevice.unit_id.between(1, MAX_MODBUS_UNIT_ID),
            ),
            literal("K") + unit_id_text,
        ),
        (
            and_(
                MeasurementDevice.device_type == MeasurementDeviceType.ENERGY_METER.value,
                MeasurementDevice.unit_id.between(1, MAX_MODBUS_UNIT_ID),
            ),
            literal("LE01MP-") + unit_id_text,
        ),
        else_=None,
    )
