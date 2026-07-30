from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ClimateChamberStatus = Literal["active", "inactive"]


class ClimateChamberResponse(BaseModel):
    id: str
    code: str
    node_id: str
    bus_id: str
    bus_key: str
    name: str
    display_order: int
    status: ClimateChamberStatus
    version: int
    created_at: datetime
    updated_at: datetime


class ClimateChamberListResponse(BaseModel):
    items: list[ClimateChamberResponse]


class ClimateChamberUpdateRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    status: ClimateChamberStatus

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("climate chamber name must not be blank")
        return normalized


class MeasuredParameterResponse(BaseModel):
    metric: str
    unit: str


class MeasurementDeviceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_key: str
    device_type: str
    manufacturer: str
    model: str
    unit_id: int
    display_name: str
    designation: str | None
    connection_status: str
    status: str
    measured_parameters: list[MeasuredParameterResponse]
    created_at: datetime
    updated_at: datetime


class PhysicalSensorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sensor_position: str
    inventory_number: str
    serial_number: str | None
    calibration_status: str
    status: str
    created_at: datetime
    updated_at: datetime


class MeasurementChannelResponse(BaseModel):
    id: str
    channel_id: str
    source_channel_id: str
    device_id: str
    controller_unit_id: int
    channel_number: int
    logical_sensor_number: int
    display_name: str
    physical_sensor_count: int
    physical_sensors: list[PhysicalSensorResponse]
    metric_type: str
    unit: str
    status: str
    created_at: datetime
    updated_at: datetime


class ClimateChamberEquipmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    climate_chamber: ClimateChamberResponse = Field(serialization_alias="climateChamber")
    temperature_controllers: list[MeasurementDeviceResponse] = Field(
        serialization_alias="temperatureControllers"
    )
    temperature_channels: list[MeasurementChannelResponse] = Field(
        serialization_alias="temperatureChannels"
    )
    energy_meters: list[MeasurementDeviceResponse] = Field(
        serialization_alias="energyMeters"
    )
    energy_meter_empty_message: str | None = Field(
        default=None,
        serialization_alias="energyMeterEmptyMessage",
    )
