from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.climate_catalog.models import ClimateChamber, MeasurementBus
from app.climate_catalog.repository import (
    CatalogChannel,
    PostgresClimateCatalogRepository,
)
from app.db import Database, TelemetryLatest, TelemetrySample
from app.nodes.domain import NodeState, normalize_node_id
from app.nodes.models import CentralNode
from app.refrigeration.channel_labels import ChannelNameStore
from app.refrigeration.commissioned_channels import (
    CommissionedTemperature,
    CommissionedTemperatureInventory,
    section_temperature,
)
from app.refrigeration.equipment_repository import (
    DEFAULT_ORGANIZATION_ID,
    EquipmentNotFoundError,
    EquipmentVersionConflictError,
)
from app.refrigeration.lifecycle_repository import (
    EquipmentLifecycleRepositoryError,
    EquipmentRetiredError,
    SensorBindingConflictError,
    SensorChannelNotFoundError,
)
from app.refrigeration.models import (
    EquipmentSensorBinding,
    RefrigerationEquipmentRecord,
    RefrigerationLayoutDraft,
)
from app.refrigeration.schemas import (
    DEFAULT_SENSOR_SLOT_CAPACITY,
    SensorBindingConfigurationItem,
    SensorConfigurationWrite,
)
from app.security.repository import AuditEventInput, SecurityRepository


class ClimateChamberNotFoundError(EquipmentLifecycleRepositoryError):
    code = "climate_chamber_not_found"


class SensorConfigurationCapacityError(EquipmentLifecycleRepositoryError):
    code = "sensor_configuration_capacity_exceeded"


class SensorConfigurationDraftVersionConflictError(EquipmentLifecycleRepositoryError):
    code = "layout_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"layout version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclass(frozen=True, slots=True)
class ClimateChamberChannel:
    channel_id: str
    metric: str
    unit: str
    latest_value: float | None
    quality: str
    captured_at: datetime
    binding: EquipmentSensorBinding | None
    controller_label: str | None = None
    display_name: str | None = None
    input_number: int | None = None
    selectable: bool = True
    sample_valid_until: datetime | None = None


@dataclass(frozen=True, slots=True)
class SensorConfigurationMutation:
    equipment: RefrigerationEquipmentRecord
    bindings: list[EquipmentSensorBinding]
    draft: RefrigerationLayoutDraft


@dataclass(frozen=True, slots=True)
class EquipmentChannelScope:
    climate_chamber_id: str | None
    climate_chamber_code: str | None
    node_id: str
    bus_id: str | None
    bus_key: str | None
    allowed_channel_ids: frozenset[str]


class PostgresSensorConfigurationRepository:
    def __init__(
        self,
        database: Database,
        *,
        climate_catalog_repository: PostgresClimateCatalogRepository | None = None,
        read_commissioned: Callable[[], CommissionedTemperatureInventory | None] | None = None,
        commissioned_organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> None:
        self._engine = database.engine
        self._climate_catalog_repository = (
            climate_catalog_repository
            or PostgresClimateCatalogRepository(database)
        )

        self._read_commissioned = read_commissioned
        self._commissioned_organization_id = commissioned_organization_id

    def list_scheme_channels(
        self,
        equipment: RefrigerationEquipmentRecord,
        current_bindings: list[EquipmentSensorBinding],
        *,
        organization_id: str,
    ) -> list[ClimateChamberChannel]:
        inventory = self._read_inventory(organization_id)
        with Session(self._engine, expire_on_commit=False) as session:
            if equipment.climate_chamber_id:
                _, legacy = self.list_climate_chamber_channels(
                    equipment.climate_chamber_id, organization_id=organization_id
                )
            elif equipment.node_id:
                _, legacy = self._legacy_node_channels(
                    equipment.node_id, organization_id=organization_id
                )
            else:
                legacy = []
            commissioned = self._authorized_inventory(session, equipment, organization_id, inventory)
            node_id = equipment.node_id or (commissioned.node_id if commissioned else None)
            active = {item.channel_id: item for item in commissioned.channels} if commissioned else {}
            section_rows = dict(active)
            for binding in current_bindings:
                identity = section_temperature(binding.channel_id)
                if identity and binding.node_id == node_id:
                    section_rows.setdefault(identity.channel_id, identity)
            rows = {item.channel_id: item for item in legacy if not section_temperature(item.channel_id)}
            if node_id and section_rows:
                rows.update(
                    self._section_channel_rows(
                        session, equipment, node_id, active, section_rows,
                        show_samples=self._owns_node(session, organization_id, node_id),
                    )
                )
            session.expunge_all()
            return list(rows.values())

    def _read_inventory(self, organization_id: str) -> CommissionedTemperatureInventory | None:
        if self._read_commissioned and organization_id == self._commissioned_organization_id:
            return self._read_commissioned()
        return None

    @staticmethod
    def _owns_node(session: Session, organization_id: str, node_id: str) -> bool:
        owners = session.execute(
            select(CentralNode.organization_id, CentralNode.state)
            .where(CentralNode.node_id == node_id)
            .limit(2)
        ).all()
        return len(owners) == 1 and tuple(owners[0]) == (organization_id, NodeState.ACTIVE.value)

    def _authorized_inventory(
        self,
        session: Session,
        equipment: RefrigerationEquipmentRecord,
        organization_id: str,
        inventory: CommissionedTemperatureInventory | None,
    ) -> CommissionedTemperatureInventory | None:
        if inventory and equipment.node_id in (None, inventory.node_id) and self._owns_node(
            session, organization_id, inventory.node_id
        ):
            return inventory
        return None

    @staticmethod
    def _section_channel_rows(
        session: Session,
        equipment: RefrigerationEquipmentRecord,
        node_id: str,
        active: dict[str, CommissionedTemperature],
        candidates: dict[str, CommissionedTemperature],
        *,
        show_samples: bool,
    ) -> dict[str, ClimateChamberChannel]:
        bindings = session.scalars(
            select(EquipmentSensorBinding).where(
                EquipmentSensorBinding.organization_id == equipment.organization_id,
                EquipmentSensorBinding.node_id == node_id,
                EquipmentSensorBinding.channel_id.in_(candidates),
                EquipmentSensorBinding.unbound_at.is_(None),
            )
        )
        by_channel = {binding.channel_id: binding for binding in bindings}
        latest = {}
        if show_samples:
            latest = {
                sample.channel_id: sample
                for sample in session.scalars(
                    select(TelemetryLatest).where(
                        TelemetryLatest.node_id == node_id,
                        TelemetryLatest.metric == "temperature.probe",
                        TelemetryLatest.unit == "degC",
                        tuple_(TelemetryLatest.equipment_id, TelemetryLatest.channel_id).in_(
                            [(item.equipment_id, item.channel_id) for item in candidates.values()]
                        ),
                    )
                )
            }
        labels = ChannelNameStore._names(
            session, equipment.organization_id, node_id, list(candidates),
        )
        rows = {}
        now = datetime.now(UTC)
        for channel_id, item in candidates.items():
            sample = latest.get(channel_id)
            captured_at = (sample.captured_at if sample else equipment.updated_at)
            if captured_at.tzinfo is None:
                captured_at = captured_at.replace(tzinfo=UTC)
            valid_until = (
                captured_at + timedelta(seconds=min(30, sample.stale_after_seconds or 30))
                if sample else None
            )
            quality = sample.quality if sample else "no-data"
            if sample and sample.value is not None and (now >= valid_until or captured_at > now):
                quality = "stale"
            rows[channel_id] = ClimateChamberChannel(
                channel_id=channel_id,
                metric="temperature.probe",
                unit="degC",
                latest_value=sample.value if sample else None,
                quality=quality,
                captured_at=captured_at,
                binding=by_channel.get(channel_id),
                controller_label=item.controller_label,
                display_name=labels.get(channel_id) or f"{item.controller_label.split(' · ')[0]} · Вхід {item.input_number}",
                input_number=item.input_number,
                selectable=channel_id in active,
                sample_valid_until=valid_until,
            )
        return rows

    def list_climate_chamber_channels(
        self,
        chamber_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> tuple[str, list[ClimateChamberChannel]]:
        chamber, bus, catalog_channels = (
            self._climate_catalog_repository.list_channels_for_chamber(
                chamber_id,
                organization_id=organization_id,
            )
        )
        if chamber is None or bus is None:
            return self._legacy_node_channels(
                chamber_id,
                organization_id=organization_id,
            )
        with Session(self._engine, expire_on_commit=False) as session:
            rows = self._catalog_channel_rows(
                session,
                organization_id=organization_id,
                chamber=chamber,
                bus=bus,
                catalog_channels=catalog_channels,
            )
            session.expunge_all()
            return bus.node_id, rows

    def replace_configuration(
        self,
        equipment_id: str,
        payload: SensorConfigurationWrite,
        *,
        expected_equipment_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> SensorConfigurationMutation:
        now = datetime.now(UTC)
        inventory = self._read_inventory(organization_id) if payload.bindings else None
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    equipment = self._locked_equipment(
                        session,
                        organization_id,
                        equipment_id,
                    )
                    self._check_equipment_version(
                        equipment,
                        expected_equipment_version,
                    )
                    self._require_mutable(equipment)
                    current = list(
                        session.scalars(
                            select(EquipmentSensorBinding)
                            .where(
                                EquipmentSensorBinding.organization_id
                                == organization_id,
                                EquipmentSensorBinding.equipment_id == equipment_id,
                                EquipmentSensorBinding.unbound_at.is_(None),
                            )
                            .with_for_update()
                        )
                    )
                    scope = self._equipment_channel_scope(
                        session,
                        equipment,
                        organization_id=organization_id,
                        current_bindings=current,
                        inventory=inventory,
                    )
                    if len(payload.bindings) > DEFAULT_SENSOR_SLOT_CAPACITY:
                        raise SensorConfigurationCapacityError(
                            "sensor configuration exceeds the equipment slot capacity"
                        )
                    draft = self._locked_draft(
                        session,
                        organization_id,
                        equipment_id,
                    )
                    if draft.version != payload.expected_draft_version:
                        raise SensorConfigurationDraftVersionConflictError(
                            expected_version=payload.expected_draft_version,
                            actual_version=draft.version,
                        )
                    requested_channel_ids = {
                        item.channel_id for item in payload.bindings
                    }
                    missing = sorted(
                        requested_channel_ids - scope.allowed_channel_ids
                    )
                    if missing:
                        scope_name = (
                            scope.climate_chamber_code
                            if scope.climate_chamber_code is not None
                            else scope.node_id
                        )
                        raise SensorChannelNotFoundError(
                            "channels are not available in measurement scope "
                            f"{scope_name!r}: " + ", ".join(missing)
                        )
                    if requested_channel_ids:
                        conflicts = list(
                            session.scalars(
                                select(EquipmentSensorBinding)
                                .where(
                                    EquipmentSensorBinding.organization_id
                                    == organization_id,
                                    EquipmentSensorBinding.node_id == scope.node_id,
                                    EquipmentSensorBinding.channel_id.in_(
                                        requested_channel_ids
                                    ),
                                    EquipmentSensorBinding.unbound_at.is_(None),
                                )
                                .with_for_update()
                            )
                        )
                        foreign = next(
                            (
                                binding
                                for binding in conflicts
                                if binding.equipment_id != equipment_id
                            ),
                            None,
                        )
                        if foreign is not None:
                            raise SensorBindingConflictError(
                                f"channel {foreign.channel_id!r} is already bound to "
                                f"{foreign.equipment_id}:{foreign.slot_key}"
                            )
                    before = {
                        "equipment_version": equipment.version,
                        "draft_version": draft.version,
                        "climate_chamber_id": scope.climate_chamber_id,
                        "node_id": scope.node_id,
                        "bus_id": scope.bus_id,
                        "bindings": [
                            _binding_snapshot(binding) for binding in current
                        ],
                        "placements": list(draft.placements),
                    }
                    desired_by_slot = {
                        item.slot_key: item for item in payload.bindings
                    }
                    current_by_slot = {
                        binding.slot_key: binding for binding in current
                    }
                    active: list[EquipmentSensorBinding] = []
                    bindings_changed = False
                    for slot_key, binding in current_by_slot.items():
                        desired = desired_by_slot.get(slot_key)
                        if desired is not None and _binding_matches(
                            binding,
                            desired,
                        ):
                            active.append(binding)
                            continue
                        binding.unbound_by = actor_id.strip()
                        binding.unbound_at = now
                        binding.version += 1
                        bindings_changed = True
                    for desired in payload.bindings:
                        current_binding = current_by_slot.get(desired.slot_key)
                        if current_binding is not None and _binding_matches(
                            current_binding,
                            desired,
                        ):
                            continue
                        binding = EquipmentSensorBinding(
                            id=str(uuid4()),
                            organization_id=organization_id,
                            equipment_id=equipment_id,
                            node_id=scope.node_id,
                            channel_id=desired.channel_id,
                            slot_key=desired.slot_key,
                            label=desired.label,
                            side=desired.side,
                            shelf=desired.shelf,
                            position=desired.position,
                            version=1,
                            bound_by=actor_id.strip(),
                            bound_at=now,
                            unbound_by=None,
                            unbound_at=None,
                        )
                        session.add(binding)
                        active.append(binding)
                        bindings_changed = True
                    placements = [
                        {
                            "sensor_id": item.channel_id,
                            "x": item.x,
                            "y": item.y,
                        }
                        for item in payload.bindings
                    ]
                    placements_changed = placements != list(draft.placements)
                    if placements_changed:
                        draft.placements = placements
                        draft.version += 1
                        draft.updated_at = now
                    if bindings_changed:
                        if payload.bindings and equipment.node_id is None:
                            equipment.node_id = scope.node_id
                        if len(payload.bindings) > equipment.total_sensors:
                            equipment.total_sensors = DEFAULT_SENSOR_SLOT_CAPACITY
                        equipment.version += 1
                        equipment.updated_at = now
                    session.flush()
                    active.sort(
                        key=lambda item: (
                            item.side,
                            item.shelf,
                            item.position,
                            item.slot_key,
                        )
                    )
                    if (
                        audit_repository is not None
                        and audit_event is not None
                        and (bindings_changed or placements_changed)
                    ):
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=equipment_id,
                                before_snapshot=before,
                                after_snapshot={
                                    "equipment_version": equipment.version,
                                    "draft_version": draft.version,
                                    "climate_chamber_id": scope.climate_chamber_id,
                                    "climate_chamber_code": scope.climate_chamber_code,
                                    "node_id": scope.node_id,
                                    "bus_id": scope.bus_id,
                                    "bus_key": scope.bus_key,
                                    "bindings": [
                                        _binding_snapshot(binding)
                                        for binding in active
                                    ],
                                    "placements": list(draft.placements),
                                },
                            ),
                            session=session,
                        )
                session.expunge_all()
                return SensorConfigurationMutation(
                    equipment=equipment,
                    bindings=active,
                    draft=draft,
                )
        except IntegrityError as error:
            raise SensorBindingConflictError(
                "sensor configuration was concurrently changed by another operator"
            ) from error

    def _equipment_channel_scope(
        self,
        session: Session,
        equipment: RefrigerationEquipmentRecord,
        *,
        organization_id: str,
        current_bindings: list[EquipmentSensorBinding],
        inventory: CommissionedTemperatureInventory | None = None,
    ) -> EquipmentChannelScope:
        inventory = self._authorized_inventory(session, equipment, organization_id, inventory)
        section_ids = {item.channel_id for item in inventory.channels} if inventory else set()
        bound_ids = {binding.channel_id for binding in current_bindings}
        if equipment.climate_chamber_id is not None:
            chamber, bus, channels = (
                self._climate_catalog_repository.list_channels_for_chamber(
                    equipment.climate_chamber_id,
                    organization_id=organization_id,
                )
            )
            if chamber is None or bus is None:
                raise ClimateChamberNotFoundError(
                    f"active climate chamber {equipment.climate_chamber_id!r} was not found"
                )
            if equipment.node_id != bus.node_id:
                raise ClimateChamberNotFoundError(
                    "equipment transport node does not match the selected chamber bus"
                )
            return EquipmentChannelScope(
                climate_chamber_id=chamber.id,
                climate_chamber_code=chamber.code,
                node_id=bus.node_id,
                bus_id=bus.id,
                bus_key=bus.bus_key,
                allowed_channel_ids=frozenset(
                    {
                        item.channel.channel_id for item in channels
                        if section_temperature(item.channel.channel_id) is None
                    } | section_ids | bound_ids
                ),
            )

        if equipment.node_id is None:
            if inventory is None:
                raise ClimateChamberNotFoundError("No authorized measurement node is available")
            return EquipmentChannelScope(
                climate_chamber_id=None,
                climate_chamber_code=None,
                node_id=inventory.node_id,
                bus_id=None,
                bus_key=None,
                allowed_channel_ids=frozenset(section_ids),
            )
        normalized_node_id = normalize_node_id(equipment.node_id)
        node = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == organization_id,
                CentralNode.node_id == normalized_node_id,
                CentralNode.state != NodeState.REVOKED.value,
            )
        )
        if node is None:
            raise ClimateChamberNotFoundError(
                f"active legacy node {normalized_node_id!r} was not found"
            )
        telemetry_channels = set(
            session.scalars(
                select(TelemetrySample.channel_id)
                .where(TelemetrySample.node_id == normalized_node_id)
                .distinct()
            )
        )
        telemetry_channels = {
            channel_id for channel_id in telemetry_channels if section_temperature(channel_id) is None
        }
        telemetry_channels.update(bound_ids | section_ids)
        return EquipmentChannelScope(
            climate_chamber_id=None,
            climate_chamber_code=None,
            node_id=normalized_node_id,
            bus_id=None,
            bus_key=None,
            allowed_channel_ids=frozenset(telemetry_channels),
        )

    def _catalog_channel_rows(
        self,
        session: Session,
        *,
        organization_id: str,
        chamber: ClimateChamber,
        bus: MeasurementBus,
        catalog_channels: tuple[CatalogChannel, ...],
    ) -> list[ClimateChamberChannel]:
        channel_ids = [item.channel.channel_id for item in catalog_channels]
        source_ids = [
            item.channel.source_channel_id for item in catalog_channels
        ]
        bindings = list(
            session.scalars(
                select(EquipmentSensorBinding).where(
                    EquipmentSensorBinding.organization_id == organization_id,
                    EquipmentSensorBinding.node_id == bus.node_id,
                    EquipmentSensorBinding.channel_id.in_(channel_ids),
                    EquipmentSensorBinding.unbound_at.is_(None),
                )
            )
        )
        by_channel = {binding.channel_id: binding for binding in bindings}
        latest_samples = self._latest_samples(
            session,
            node_id=bus.node_id,
            channel_ids=source_ids,
        )
        return [
            ClimateChamberChannel(
                channel_id=item.channel.channel_id,
                metric=item.channel.metric_type,
                unit=item.channel.unit,
                latest_value=(
                    latest_samples[item.channel.source_channel_id].value
                    if item.channel.source_channel_id in latest_samples
                    else None
                ),
                quality=(
                    latest_samples[item.channel.source_channel_id].quality
                    if item.channel.source_channel_id in latest_samples
                    else "no-data"
                ),
                captured_at=(
                    latest_samples[item.channel.source_channel_id].captured_at
                    if item.channel.source_channel_id in latest_samples
                    else item.channel.created_at
                ),
                binding=by_channel.get(item.channel.channel_id),
            )
            for item in catalog_channels
        ]

    def _legacy_node_channels(
        self,
        node_id: str,
        *,
        organization_id: str,
    ) -> tuple[str, list[ClimateChamberChannel]]:
        normalized_node_id = normalize_node_id(node_id)
        with Session(self._engine, expire_on_commit=False) as session:
            node = session.scalar(
                select(CentralNode).where(
                    CentralNode.organization_id == organization_id,
                    CentralNode.node_id == normalized_node_id,
                    CentralNode.state != NodeState.REVOKED.value,
                )
            )
            if node is None:
                raise ClimateChamberNotFoundError(
                    f"climate chamber or node {node_id!r} was not found"
                )
            bindings = list(
                session.scalars(
                    select(EquipmentSensorBinding).where(
                        EquipmentSensorBinding.organization_id == organization_id,
                        EquipmentSensorBinding.node_id == normalized_node_id,
                        EquipmentSensorBinding.unbound_at.is_(None),
                    )
                )
            )
            by_channel = {binding.channel_id: binding for binding in bindings}
            samples = list(
                session.scalars(
                    select(TelemetrySample)
                    .where(TelemetrySample.node_id == normalized_node_id)
                    .order_by(
                        TelemetrySample.captured_at.desc(),
                        TelemetrySample.id.desc(),
                    )
                    .limit(5000)
                )
            )
            latest: dict[str, ClimateChamberChannel] = {}
            for sample in samples:
                latest.setdefault(
                    sample.channel_id,
                    ClimateChamberChannel(
                        channel_id=sample.channel_id,
                        metric=sample.metric,
                        unit=sample.unit,
                        latest_value=sample.value,
                        quality=sample.quality,
                        captured_at=sample.captured_at,
                        binding=by_channel.get(sample.channel_id),
                    ),
                )
            for binding in bindings:
                if binding.channel_id in latest:
                    continue
                latest[binding.channel_id] = ClimateChamberChannel(
                    channel_id=binding.channel_id,
                    metric="unknown",
                    unit="—",
                    latest_value=None,
                    quality="no-data",
                    captured_at=binding.bound_at,
                    binding=binding,
                )
            session.expunge_all()
            return normalized_node_id, sorted(
                latest.values(),
                key=lambda item: item.channel_id,
            )

    @staticmethod
    def _latest_samples(
        session: Session,
        *,
        node_id: str,
        channel_ids: list[str],
    ) -> dict[str, TelemetryLatest]:
        if not channel_ids:
            return {}
        samples = list(
            session.scalars(
                select(TelemetryLatest)
                .where(
                    TelemetryLatest.node_id == node_id,
                    TelemetryLatest.channel_id.in_(channel_ids),
                )
                .order_by(
                    TelemetryLatest.captured_at.desc(),
                    TelemetryLatest.id.desc(),
                )
            )
        )
        latest: dict[str, TelemetryLatest] = {}
        for sample in samples:
            latest.setdefault(sample.channel_id, sample)
        return latest

    @staticmethod
    def _locked_equipment(
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        equipment = session.scalar(
            select(RefrigerationEquipmentRecord)
            .where(
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.id == equipment_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if equipment is None:
            raise EquipmentNotFoundError(
                f"equipment {equipment_id!r} was not found"
            )
        return equipment

    @staticmethod
    def _locked_draft(
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationLayoutDraft:
        draft = session.scalar(
            select(RefrigerationLayoutDraft)
            .where(
                RefrigerationLayoutDraft.organization_id == organization_id,
                RefrigerationLayoutDraft.equipment_id == equipment_id,
            )
            .with_for_update()
        )
        if draft is None:
            raise EquipmentNotFoundError(
                f"layout draft for {equipment_id!r} was not found"
            )
        return draft

    @staticmethod
    def _check_equipment_version(
        equipment: RefrigerationEquipmentRecord,
        expected_version: int,
    ) -> None:
        if equipment.version != expected_version:
            raise EquipmentVersionConflictError(
                expected_version=expected_version,
                actual_version=equipment.version,
            )

    @staticmethod
    def _require_mutable(
        equipment: RefrigerationEquipmentRecord,
    ) -> None:
        if (
            equipment.lifecycle_status == "retired"
            or equipment.deleted_at is not None
        ):
            raise EquipmentRetiredError(
                "retired equipment sensor configuration is read-only"
            )


def _binding_matches(
    binding: EquipmentSensorBinding,
    desired: SensorBindingConfigurationItem,
) -> bool:
    return (
        binding.channel_id == desired.channel_id
        and binding.label == desired.label
        and binding.side == desired.side
        and binding.shelf == desired.shelf
        and binding.position == desired.position
    )


def _binding_snapshot(
    binding: EquipmentSensorBinding,
) -> dict[str, object]:
    return {
        "id": binding.id,
        "equipment_id": binding.equipment_id,
        "node_id": binding.node_id,
        "channel_id": binding.channel_id,
        "slot_key": binding.slot_key,
        "label": binding.label,
        "side": binding.side,
        "shelf": binding.shelf,
        "position": binding.position,
        "version": binding.version,
        "bound_by": binding.bound_by,
        "bound_at": binding.bound_at.isoformat(),
        "unbound_by": binding.unbound_by,
        "unbound_at": (
            binding.unbound_at.isoformat()
            if binding.unbound_at is not None
            else None
        ),
    }
