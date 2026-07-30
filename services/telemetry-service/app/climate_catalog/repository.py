from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.climate_catalog.domain import (
    CLIMATE_CHAMBERS,
    MEASUREMENT_BUSES,
    PHYSICAL_SENSOR_POSITIONS,
    MeasurementDeviceType,
    iter_temperature_channels,
)
from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
    PhysicalSensor,
)
from app.db import Database
from app.nodes.models import CentralNode
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.security.repository import AuditEventInput, SecurityRepository


class ClimateCatalogRepositoryError(RuntimeError):
    code = "climate_catalog_repository_error"


class ClimateChamberNotFoundError(ClimateCatalogRepositoryError):
    code = "climate_chamber_not_found"


class ClimateChamberVersionConflictError(ClimateCatalogRepositoryError):
    code = "climate_chamber_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"climate chamber version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclass(frozen=True, slots=True)
class CatalogSeedResult:
    skipped: bool
    nodes_created: int = 0
    buses_created: int = 0
    chambers_created: int = 0
    devices_created: int = 0
    channels_created: int = 0
    physical_sensors_created: int = 0

    @property
    def changed(self) -> bool:
        return any(
            (
                self.nodes_created,
                self.buses_created,
                self.chambers_created,
                self.devices_created,
                self.channels_created,
                self.physical_sensors_created,
            )
        )


@dataclass(frozen=True, slots=True)
class CatalogChannel:
    channel: MeasurementChannel
    device: MeasurementDevice
    physical_sensors: tuple[PhysicalSensor, ...]


@dataclass(frozen=True, slots=True)
class ClimateChamberEquipmentCatalog:
    chamber: ClimateChamber
    bus: MeasurementBus
    temperature_controllers: tuple[MeasurementDevice, ...]
    temperature_channels: tuple[CatalogChannel, ...]
    energy_meters: tuple[MeasurementDevice, ...]


class PostgresClimateCatalogRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository or SecurityRepository(database)

    def seed_default_catalog(
        self,
        *,
        organization_id: str,
        actor_subject: str = "system:climate-catalog-seed",
    ) -> CatalogSeedResult:
        now = datetime.now(UTC)
        counters = {
            "nodes_created": 0,
            "buses_created": 0,
            "chambers_created": 0,
            "devices_created": 0,
            "channels_created": 0,
            "physical_sensors_created": 0,
        }
        inserted_by_chamber: dict[str, dict[str, int]] = {
            item.code.value: {
                "climate_chambers": 0,
                "temperature_controllers": 0,
                "temperature_channels": 0,
                "physical_sensors": 0,
                "energy_meters": 0,
            }
            for item in CLIMATE_CHAMBERS
        }
        changed_codes: set[str] = set()

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                organization = session.get(SecurityOrganization, organization_id)
                if organization is None or not organization.is_active:
                    return CatalogSeedResult(skipped=True)

                nodes = {
                    row.node_id: row
                    for row in session.scalars(
                        select(CentralNode).where(
                            CentralNode.organization_id == organization_id
                        )
                    )
                }
                for definition in MEASUREMENT_BUSES:
                    if definition.node_id in nodes:
                        continue
                    node = CentralNode(
                        id=_stable_uuid(
                            f"central-node:{organization_id}:{definition.node_id}"
                        ),
                        organization_id=organization_id,
                        node_id=definition.node_id,
                        display_name="NEXOLAB Edge 01",
                        state="active",
                        state_reason="Provisioned by measurement catalog seed",
                        clock_warning_ms=30_000,
                        clock_critical_ms=120_000,
                        last_seen_at=None,
                        last_clock_offset_ms=None,
                        clock_status="unknown",
                        clock_observed_at=None,
                        created_by=actor_subject,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(node)
                    nodes[definition.node_id] = node
                    counters["nodes_created"] += 1
                session.flush()

                buses_by_key = {
                    row.bus_key: row
                    for row in session.scalars(
                        select(MeasurementBus).where(
                            MeasurementBus.organization_id == organization_id
                        )
                    )
                }
                for definition in MEASUREMENT_BUSES:
                    if definition.bus_key in buses_by_key:
                        continue
                    bus = MeasurementBus(
                        id=_stable_uuid(
                            f"measurement-bus:{organization_id}:{definition.bus_key}"
                        ),
                        organization_id=organization_id,
                        node_id=definition.node_id,
                        bus_key=definition.bus_key,
                        display_name=definition.display_name,
                        protocol=definition.protocol,
                        port=definition.port,
                        baudrate=definition.baudrate,
                        data_bits=definition.data_bits,
                        parity=definition.parity,
                        stop_bits=definition.stop_bits,
                        status="active",
                        version=1,
                        created_by=actor_subject,
                        updated_by=actor_subject,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(bus)
                    buses_by_key[definition.bus_key] = bus
                    counters["buses_created"] += 1
                session.flush()

                chambers_by_code = {
                    row.code: row
                    for row in session.scalars(
                        select(ClimateChamber).where(
                            ClimateChamber.organization_id == organization_id
                        )
                    )
                }
                for definition in CLIMATE_CHAMBERS:
                    code = definition.code.value
                    if code in chambers_by_code:
                        continue
                    chamber = ClimateChamber(
                        id=_stable_uuid(f"climate-chamber:{organization_id}:{code}"),
                        organization_id=organization_id,
                        bus_id=buses_by_key[definition.bus_key].id,
                        code=code,
                        name=definition.name,
                        display_order=definition.display_order,
                        status="active",
                        version=1,
                        created_by=actor_subject,
                        updated_by=actor_subject,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(chamber)
                    chambers_by_code[code] = chamber
                    counters["chambers_created"] += 1
                    inserted_by_chamber[code]["climate_chambers"] += 1
                    changed_codes.add(code)
                session.flush()

                devices_by_key = {
                    row.business_key: row
                    for row in session.scalars(
                        select(MeasurementDevice).where(
                            MeasurementDevice.organization_id == organization_id
                        )
                    )
                }
                for definition in CLIMATE_CHAMBERS:
                    code = definition.code.value
                    chamber = chambers_by_code[code]
                    bus = buses_by_key[definition.bus_key]
                    for unit_id in range(
                        definition.controller_start,
                        definition.controller_end + 1,
                    ):
                        business_key = f"DIXELL-{unit_id}"
                        if business_key in devices_by_key:
                            continue
                        device = MeasurementDevice(
                            id=_stable_uuid(
                                f"measurement-device:{organization_id}:{business_key}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            bus_id=bus.id,
                            business_key=business_key,
                            device_type=MeasurementDeviceType.TEMPERATURE_CONTROLLER.value,
                            manufacturer="Dixell",
                            model="XJP60D",
                            unit_id=unit_id,
                            display_name=f"Dixell №{unit_id}",
                            designation=None,
                            connection_status="unknown",
                            status="active",
                            measured_parameters=[
                                {"metric": "temperature.probe", "unit": "degC"}
                            ],
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(device)
                        devices_by_key[business_key] = device
                        counters["devices_created"] += 1
                        inserted_by_chamber[code]["temperature_controllers"] += 1
                        changed_codes.add(code)
                    for meter in definition.energy_meters:
                        business_key = f"LE01MP-{meter.unit_id}"
                        if business_key in devices_by_key:
                            continue
                        device = MeasurementDevice(
                            id=_stable_uuid(
                                f"measurement-device:{organization_id}:{business_key}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            bus_id=bus.id,
                            business_key=business_key,
                            device_type=MeasurementDeviceType.ENERGY_METER.value,
                            manufacturer="F&F",
                            model="LE-01MP",
                            unit_id=meter.unit_id,
                            display_name=f"{meter.designation} — LE-01MP №{meter.unit_id}",
                            designation=meter.designation,
                            connection_status="unknown",
                            status="active",
                            measured_parameters=[
                                {"metric": "electrical.voltage", "unit": "V"},
                                {"metric": "electrical.current", "unit": "A"},
                                {"metric": "electrical.power.active", "unit": "W"},
                                {"metric": "electrical.frequency", "unit": "Hz"},
                            ],
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(device)
                        devices_by_key[business_key] = device
                        counters["devices_created"] += 1
                        inserted_by_chamber[code]["energy_meters"] += 1
                        changed_codes.add(code)
                session.flush()

                channels_by_key = {
                    row.channel_id: row
                    for row in session.scalars(
                        select(MeasurementChannel).where(
                            MeasurementChannel.organization_id == organization_id
                        )
                    )
                }
                for definition in CLIMATE_CHAMBERS:
                    code = definition.code.value
                    chamber = chambers_by_code[code]
                    bus = buses_by_key[definition.bus_key]
                    for channel_definition in iter_temperature_channels(definition.code):
                        if channel_definition.channel_id in channels_by_key:
                            continue
                        device = devices_by_key[
                            f"DIXELL-{channel_definition.controller_unit_id}"
                        ]
                        channel = MeasurementChannel(
                            id=_stable_uuid(
                                "measurement-channel:"
                                f"{organization_id}:{channel_definition.channel_id}"
                            ),
                            organization_id=organization_id,
                            climate_chamber_id=chamber.id,
                            bus_id=bus.id,
                            device_id=device.id,
                            channel_id=channel_definition.channel_id,
                            source_channel_id=channel_definition.source_channel_id,
                            channel_number=channel_definition.channel_number,
                            logical_sensor_number=channel_definition.logical_sensor_number,
                            display_name=channel_definition.display_name,
                            physical_sensor_count=channel_definition.physical_sensor_count,
                            metric_type="temperature.probe",
                            unit="degC",
                            status="active",
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(channel)
                        channels_by_key[channel_definition.channel_id] = channel
                        counters["channels_created"] += 1
                        inserted_by_chamber[code]["temperature_channels"] += 1
                        changed_codes.add(code)
                session.flush()

                sensors_by_key = {
                    (row.channel_id, row.sensor_position): row
                    for row in session.scalars(
                        select(PhysicalSensor).where(
                            PhysicalSensor.organization_id == organization_id
                        )
                    )
                }
                for definition in CLIMATE_CHAMBERS:
                    code = definition.code.value
                    chamber = chambers_by_code[code]
                    for channel_definition in iter_temperature_channels(definition.code):
                        channel = channels_by_key[channel_definition.channel_id]
                        inventory_numbers = (
                            channel_definition.physical_sensor_inventory_numbers
                        )
                        positions = PHYSICAL_SENSOR_POSITIONS[
                            : channel_definition.physical_sensor_count
                        ]
                        for position, inventory_number in zip(
                            positions,
                            inventory_numbers,
                            strict=True,
                        ):
                            sensor_key = (channel.id, position)
                            if sensor_key in sensors_by_key:
                                continue
                            sensor = PhysicalSensor(
                                id=_stable_uuid(
                                    "physical-sensor:"
                                    f"{organization_id}:{code}:{inventory_number}"
                                ),
                                organization_id=organization_id,
                                climate_chamber_id=chamber.id,
                                channel_id=channel.id,
                                sensor_position=position,
                                inventory_number=inventory_number,
                                serial_number=None,
                                calibration_status="untracked",
                                status="active",
                                created_at=now,
                                updated_at=now,
                            )
                            session.add(sensor)
                            sensors_by_key[sensor_key] = sensor
                            counters["physical_sensors_created"] += 1
                            inserted_by_chamber[code]["physical_sensors"] += 1
                            changed_codes.add(code)
                session.flush()

                for code in sorted(changed_codes):
                    chamber = chambers_by_code[code]
                    bus = next(
                        item for item in buses_by_key.values() if item.id == chamber.bus_id
                    )
                    self._security_repository.append_audit_event(
                        AuditEventInput(
                            organization_id=organization_id,
                            actor_identity_id=None,
                            actor_subject=actor_subject,
                            actor_roles=frozenset({Role.ADMINISTRATOR}),
                            action="climate_chamber.catalog.seeded",
                            entity_type="climate_chamber",
                            entity_id=chamber.id,
                            before_snapshot=None,
                            after_snapshot={
                                "code": chamber.code,
                                "node_id": bus.node_id,
                                "bus_id": bus.id,
                                "bus_key": bus.bus_key,
                                "name": chamber.name,
                                "inserted": inserted_by_chamber[code],
                            },
                            reason="Idempotent default measurement catalog seed",
                        ),
                        session=session,
                    )

        return CatalogSeedResult(skipped=False, **counters)

    def list_chambers(
        self,
        *,
        organization_id: str,
        include_inactive: bool = False,
    ) -> list[ClimateChamber]:
        statement = select(ClimateChamber).where(
            ClimateChamber.organization_id == organization_id
        )
        if not include_inactive:
            statement = statement.where(ClimateChamber.status == "active")
        statement = statement.order_by(
            ClimateChamber.display_order.asc(),
            ClimateChamber.code.asc(),
        )
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            session.expunge_all()
            return rows

    def get_chamber(
        self,
        identifier: str,
        *,
        organization_id: str,
        include_inactive: bool = False,
    ) -> ClimateChamber:
        with Session(self._engine, expire_on_commit=False) as session:
            chamber = self._chamber_in_session(
                session,
                identifier,
                organization_id=organization_id,
                include_inactive=include_inactive,
            )
            session.expunge(chamber)
            return chamber

    def get_chamber_transport(
        self,
        identifier: str,
        *,
        organization_id: str,
    ) -> MeasurementBus:
        with Session(self._engine, expire_on_commit=False) as session:
            chamber = self._chamber_in_session(
                session,
                identifier,
                organization_id=organization_id,
            )
            bus = session.scalar(
                select(MeasurementBus).where(
                    MeasurementBus.organization_id == organization_id,
                    MeasurementBus.id == chamber.bus_id,
                    MeasurementBus.status == "active",
                )
            )
            if bus is None:
                raise ClimateCatalogRepositoryError(
                    f"active measurement bus for chamber {identifier!r} was not found"
                )
            session.expunge(bus)
            return bus

    def get_equipment_catalog(
        self,
        identifier: str,
        *,
        organization_id: str,
    ) -> ClimateChamberEquipmentCatalog:
        with Session(self._engine, expire_on_commit=False) as session:
            chamber = self._chamber_in_session(
                session,
                identifier,
                organization_id=organization_id,
            )
            bus = session.scalar(
                select(MeasurementBus).where(
                    MeasurementBus.organization_id == organization_id,
                    MeasurementBus.id == chamber.bus_id,
                )
            )
            if bus is None:
                raise ClimateCatalogRepositoryError(
                    f"measurement bus for chamber {identifier!r} was not found"
                )
            devices = list(
                session.scalars(
                    select(MeasurementDevice)
                    .where(
                        MeasurementDevice.organization_id == organization_id,
                        MeasurementDevice.climate_chamber_id == chamber.id,
                        MeasurementDevice.status == "active",
                    )
                    .order_by(
                        MeasurementDevice.device_type.asc(),
                        MeasurementDevice.unit_id.asc(),
                    )
                )
            )
            controllers = tuple(
                item
                for item in devices
                if item.device_type
                == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value
            )
            energy_meters = tuple(
                sorted(
                    (
                        item
                        for item in devices
                        if item.device_type
                        == MeasurementDeviceType.ENERGY_METER.value
                    ),
                    key=lambda item: (item.designation or "", item.unit_id),
                )
            )
            channels = self._catalog_channels(
                session,
                chamber=chamber,
                organization_id=organization_id,
            )
            session.expunge_all()
            return ClimateChamberEquipmentCatalog(
                chamber=chamber,
                bus=bus,
                temperature_controllers=controllers,
                temperature_channels=channels,
                energy_meters=energy_meters,
            )

    def list_channels_for_chamber(
        self,
        identifier: str,
        *,
        organization_id: str,
    ) -> tuple[ClimateChamber | None, MeasurementBus | None, tuple[CatalogChannel, ...]]:
        with Session(self._engine, expire_on_commit=False) as session:
            try:
                chamber = self._chamber_in_session(
                    session,
                    identifier,
                    organization_id=organization_id,
                )
            except ClimateChamberNotFoundError:
                return None, None, ()
            bus = session.scalar(
                select(MeasurementBus).where(
                    MeasurementBus.organization_id == organization_id,
                    MeasurementBus.id == chamber.bus_id,
                    MeasurementBus.status == "active",
                )
            )
            if bus is None:
                return None, None, ()
            channels = self._catalog_channels(
                session,
                chamber=chamber,
                organization_id=organization_id,
            )
            session.expunge_all()
            return chamber, bus, channels

    def list_channels_for_node(
        self,
        node_id: str,
        *,
        organization_id: str,
    ) -> tuple[ClimateChamber | None, tuple[CatalogChannel, ...]]:
        """Compatibility alias for pre-catalog callers using KK1/KK2 as identifiers."""
        chamber, _bus, channels = self.list_channels_for_chamber(
            node_id,
            organization_id=organization_id,
        )
        return chamber, channels

    def has_catalog(self, *, organization_id: str) -> bool:
        with Session(self._engine) as session:
            return (
                session.scalar(
                    select(ClimateChamber.id)
                    .where(ClimateChamber.organization_id == organization_id)
                    .limit(1)
                )
                is not None
            )

    def update_chamber(
        self,
        identifier: str,
        *,
        name: str,
        status: str,
        expected_version: int,
        actor_subject: str,
        organization_id: str,
        audit_event: AuditEventInput,
    ) -> ClimateChamber:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                chamber = session.scalar(
                    select(ClimateChamber)
                    .where(
                        ClimateChamber.organization_id == organization_id,
                        or_(
                            ClimateChamber.id == identifier.strip(),
                            ClimateChamber.code == identifier.strip().upper(),
                        ),
                    )
                    .with_for_update()
                )
                if chamber is None:
                    raise ClimateChamberNotFoundError(
                        f"climate chamber {identifier!r} was not found"
                    )
                if chamber.version != expected_version:
                    raise ClimateChamberVersionConflictError(
                        expected_version=expected_version,
                        actual_version=chamber.version,
                    )
                normalized_name = " ".join(name.split())
                if not normalized_name:
                    raise ClimateCatalogRepositoryError(
                        "climate chamber name is required"
                    )
                if status not in {"active", "inactive"}:
                    raise ClimateCatalogRepositoryError(
                        "unsupported climate chamber status"
                    )
                before = _chamber_snapshot(chamber)
                chamber.name = normalized_name
                chamber.status = status
                chamber.version += 1
                chamber.updated_by = actor_subject.strip()
                chamber.updated_at = now
                self._security_repository.append_audit_event(
                    replace(
                        audit_event,
                        entity_id=chamber.id,
                        before_snapshot=before,
                        after_snapshot=_chamber_snapshot(chamber),
                    ),
                    session=session,
                )
            session.expunge(chamber)
            return chamber

    @staticmethod
    def _chamber_in_session(
        session: Session,
        identifier: str,
        *,
        organization_id: str,
        include_inactive: bool = False,
    ) -> ClimateChamber:
        normalized = identifier.strip()
        statement = select(ClimateChamber).where(
            ClimateChamber.organization_id == organization_id,
            or_(
                ClimateChamber.id == normalized,
                ClimateChamber.code == normalized.upper(),
            ),
        )
        if not include_inactive:
            statement = statement.where(ClimateChamber.status == "active")
        chamber = session.scalar(statement)
        if chamber is None:
            raise ClimateChamberNotFoundError(
                f"climate chamber {identifier!r} was not found"
            )
        return chamber

    @staticmethod
    def _catalog_channels(
        session: Session,
        *,
        chamber: ClimateChamber,
        organization_id: str,
    ) -> tuple[CatalogChannel, ...]:
        devices = {
            row.id: row
            for row in session.scalars(
                select(MeasurementDevice).where(
                    MeasurementDevice.organization_id == organization_id,
                    MeasurementDevice.climate_chamber_id == chamber.id,
                    MeasurementDevice.device_type
                    == MeasurementDeviceType.TEMPERATURE_CONTROLLER.value,
                    MeasurementDevice.status == "active",
                )
            )
        }
        if not devices:
            return ()
        channels = list(
            session.scalars(
                select(MeasurementChannel).where(
                    MeasurementChannel.organization_id == organization_id,
                    MeasurementChannel.climate_chamber_id == chamber.id,
                    MeasurementChannel.device_id.in_(list(devices)),
                    MeasurementChannel.status == "active",
                )
            )
        )
        sensors_by_channel: dict[str, list[PhysicalSensor]] = {}
        if channels:
            for sensor in session.scalars(
                select(PhysicalSensor).where(
                    PhysicalSensor.organization_id == organization_id,
                    PhysicalSensor.channel_id.in_([item.id for item in channels]),
                    PhysicalSensor.status == "active",
                )
            ):
                sensors_by_channel.setdefault(sensor.channel_id, []).append(sensor)
        channels.sort(
            key=lambda item: (
                devices[item.device_id].unit_id,
                item.channel_number,
                item.logical_sensor_number,
            )
        )
        return tuple(
            CatalogChannel(
                channel=channel,
                device=devices[channel.device_id],
                physical_sensors=tuple(
                    sorted(
                        sensors_by_channel.get(channel.id, []),
                        key=lambda item: item.sensor_position,
                    )
                ),
            )
            for channel in channels
        )


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://nexolab.local/{value}"))


def _chamber_snapshot(chamber: ClimateChamber) -> dict[str, object]:
    return {
        "id": chamber.id,
        "code": chamber.code,
        "bus_id": chamber.bus_id,
        "name": chamber.name,
        "status": chamber.status,
        "display_order": chamber.display_order,
        "version": chamber.version,
    }
