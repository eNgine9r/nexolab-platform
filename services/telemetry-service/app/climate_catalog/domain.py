from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Iterator


class ClimateCatalogError(ValueError):
    code = "climate_catalog_error"


class ClimateChamberCode(StrEnum):
    KK1 = "KK1"
    KK2 = "KK2"


class MeasurementDeviceType(StrEnum):
    TEMPERATURE_CONTROLLER = "temperature_controller"
    ENERGY_METER = "energy_meter"


class CatalogStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class MeasurementBusDefinition:
    bus_key: str
    node_id: str
    display_name: str
    protocol: str
    port: str
    baudrate: int
    data_bits: int
    parity: str
    stop_bits: int


@dataclass(frozen=True, slots=True)
class EnergyMeterDefinition:
    unit_id: int
    designation: str


@dataclass(frozen=True, slots=True)
class ClimateChamberDefinition:
    code: ClimateChamberCode
    name: str
    display_order: int
    bus_key: str
    controller_start: int
    controller_end: int
    logical_sensor_start: int
    physical_sensor_count: int
    energy_meters: tuple[EnergyMeterDefinition, ...]

    @property
    def controller_count(self) -> int:
        return self.controller_end - self.controller_start + 1

    @property
    def logical_channel_count(self) -> int:
        return self.controller_count * CHANNELS_PER_DIXELL

    @property
    def logical_sensor_end(self) -> int:
        return self.logical_sensor_start + self.logical_channel_count - 1


@dataclass(frozen=True, slots=True)
class TemperatureChannelDefinition:
    chamber_code: ClimateChamberCode
    bus_key: str
    controller_unit_id: int
    channel_number: int
    channel_id: str
    source_channel_id: str
    display_name: str
    logical_sensor_number: int
    physical_sensor_count: int

    @property
    def physical_sensor_inventory_numbers(self) -> tuple[str, ...]:
        if self.physical_sensor_count == 1:
            return (str(self.logical_sensor_number),)
        positions = PHYSICAL_SENSOR_POSITIONS[: self.physical_sensor_count]
        return tuple(f"{self.logical_sensor_number}-{position}" for position in positions)


CHANNELS_PER_DIXELL: Final = 6
PHYSICAL_SENSOR_POSITIONS: Final = ("A", "B")
DEFAULT_EDGE_NODE_ID: Final = "edge-01"
DEFAULT_RS485_BUS_KEY: Final = "rs485-main-01"

MEASUREMENT_BUSES: Final[tuple[MeasurementBusDefinition, ...]] = (
    MeasurementBusDefinition(
        bus_key=DEFAULT_RS485_BUS_KEY,
        node_id=DEFAULT_EDGE_NODE_ID,
        display_name="Основна RS-485 шина",
        protocol="modbus_rtu",
        port=(
            "/dev/serial/by-id/"
            "usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0"
        ),
        baudrate=9600,
        data_bits=8,
        parity="N",
        stop_bits=1,
    ),
)

CLIMATE_CHAMBERS: Final[tuple[ClimateChamberDefinition, ...]] = (
    ClimateChamberDefinition(
        code=ClimateChamberCode.KK1,
        name="Кліматична камера №1",
        display_order=1,
        bus_key=DEFAULT_RS485_BUS_KEY,
        controller_start=126,
        controller_end=138,
        logical_sensor_start=197,
        physical_sensor_count=1,
        energy_meters=(
            EnergyMeterDefinition(unit_id=200, designation="W1"),
            EnergyMeterDefinition(unit_id=201, designation="W2"),
            EnergyMeterDefinition(unit_id=202, designation="W3"),
            EnergyMeterDefinition(unit_id=203, designation="W4"),
        ),
    ),
    ClimateChamberDefinition(
        code=ClimateChamberCode.KK2,
        name="Кліматична камера №2",
        display_order=2,
        bus_key=DEFAULT_RS485_BUS_KEY,
        controller_start=101,
        controller_end=114,
        logical_sensor_start=471,
        physical_sensor_count=2,
        energy_meters=(),
    ),
)

BUS_BY_KEY: Final = {item.bus_key: item for item in MEASUREMENT_BUSES}
CHAMBER_BY_CODE: Final = {item.code.value: item for item in CLIMATE_CHAMBERS}


def chamber_definition(value: str | ClimateChamberCode) -> ClimateChamberDefinition:
    normalized = str(value).strip().upper()
    try:
        return CHAMBER_BY_CODE[normalized]
    except KeyError as error:
        raise ClimateCatalogError(f"unsupported climate chamber code: {value!r}") from error


def logical_sensor_number(
    chamber: str | ClimateChamberCode,
    controller_unit_id: int,
    channel_number: int,
) -> int:
    definition = chamber_definition(chamber)
    _validate_controller(definition, controller_unit_id)
    _validate_channel(channel_number)
    return (
        definition.logical_sensor_start
        + (controller_unit_id - definition.controller_start) * CHANNELS_PER_DIXELL
        + (channel_number - 1)
    )


def temperature_source_channel_id(controller_unit_id: int, channel_number: int) -> str:
    if controller_unit_id < 1:
        raise ClimateCatalogError("controller unit id must be positive")
    _validate_channel(channel_number)
    return f"{controller_unit_id:03d}-{channel_number:02d}"


def temperature_channel_id(
    chamber: str | ClimateChamberCode,
    controller_unit_id: int,
    channel_number: int,
) -> str:
    definition = chamber_definition(chamber)
    _validate_controller(definition, controller_unit_id)
    return temperature_source_channel_id(controller_unit_id, channel_number)


def temperature_channel_display_name(controller_unit_id: int, channel_number: int) -> str:
    if controller_unit_id < 1:
        raise ClimateCatalogError("controller unit id must be positive")
    _validate_channel(channel_number)
    return f"Dixell №{controller_unit_id}_{channel_number}"


def iter_temperature_channels(
    chamber: str | ClimateChamberCode,
) -> Iterator[TemperatureChannelDefinition]:
    definition = chamber_definition(chamber)
    for controller_unit_id in range(definition.controller_start, definition.controller_end + 1):
        for channel_number in range(1, CHANNELS_PER_DIXELL + 1):
            source_channel_id = temperature_source_channel_id(
                controller_unit_id,
                channel_number,
            )
            yield TemperatureChannelDefinition(
                chamber_code=definition.code,
                bus_key=definition.bus_key,
                controller_unit_id=controller_unit_id,
                channel_number=channel_number,
                channel_id=source_channel_id,
                source_channel_id=source_channel_id,
                display_name=temperature_channel_display_name(
                    controller_unit_id,
                    channel_number,
                ),
                logical_sensor_number=logical_sensor_number(
                    definition.code,
                    controller_unit_id,
                    channel_number,
                ),
                physical_sensor_count=definition.physical_sensor_count,
            )


def _validate_controller(
    definition: ClimateChamberDefinition,
    controller_unit_id: int,
) -> None:
    if not definition.controller_start <= controller_unit_id <= definition.controller_end:
        raise ClimateCatalogError(
            f"controller {controller_unit_id} does not belong to {definition.code.value}"
        )


def _validate_channel(channel_number: int) -> None:
    if not 1 <= channel_number <= CHANNELS_PER_DIXELL:
        raise ClimateCatalogError(
            f"Dixell channel number must be between 1 and {CHANNELS_PER_DIXELL}"
        )
