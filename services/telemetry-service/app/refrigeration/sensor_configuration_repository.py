from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.db import Database, TelemetrySample
from app.nodes.domain import NodeState, normalize_node_id
from app.nodes.models import CentralNode
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
from app.refrigeration.schemas import SensorBindingConfigurationItem, SensorConfigurationWrite
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


@dataclass(frozen=True, slots=True)
class SensorConfigurationMutation:
    equipment: RefrigerationEquipmentRecord
    bindings: list[EquipmentSensorBinding]
    draft: RefrigerationLayoutDraft


class PostgresSensorConfigurationRepository:
    def __init__(
        self,
        database: Database,
        *,
        climate_catalog_repository: PostgresClimateCatalogRepository | None = None,
    ) -> None:
        self._engine = database.engine
        self._climate_catalog_repository = (
            climate_catalog_repository or PostgresClimateCatalogRepository(database)
        )

    def list_climate_chamber_channels(
        self,
        node_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> tuple[str, list[ClimateChamberChannel]]:
        normalized_node_id = normalize_node_id(node_id)
        with Session(self._engine, expire_on_commit=False) as session:
            self._climate_chamber(session, organization_id, normalized_node_id)
            return normalized_node_id, self._channels(
                session,
                organization_id=organization_id,
                node_id=normalized_node_id,
            )

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
                    if equipment.node_id is None:
                        raise ClimateChamberNotFoundError(
                            "select a climate chamber before configuring measurement channels"
                        )
                    self._climate_chamber(
                        session,
                        organization_id,
                        equipment.node_id,
                    )
                    if len(payload.bindings) > equipment.total_sensors:
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
                    requested_channel_ids = {
                        item.channel_id for item in payload.bindings
                    }
                    if requested_channel_ids:
                        conflicts = list(
                            session.scalars(
                                select(EquipmentSensorBinding)
                                .where(
                                    EquipmentSensorBinding.organization_id
                                    == organization_id,
                                    EquipmentSensorBinding.node_id
                                    == equipment.node_id,
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

                    observed_channels = {
                        channel.channel_id
                        for channel in self._channels(
                            session,
                            organization_id=organization_id,
                            node_id=equipment.node_id,
                        )
                    }
                    missing = sorted(requested_channel_ids - observed_channels)
                    if missing:
                        raise SensorChannelNotFoundError(
                            "channels are not available in climate chamber "
                            f"{equipment.node_id!r}: " + ", ".join(missing)
                        )

                    before = {
                        "equipment_version": equipment.version,
                        "draft_version": draft.version,
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
                            node_id=equipment.node_id,
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
                                    "climate_chamber_node_id": equipment.node_id,
                                    "bindings": [
                                        _binding_snapshot(binding)
                                        for binding in active
                                    ],
                                    "placements": list(draft.placements),
                                },
                            ),
                            session=session,
                        )

                for binding in active:
                    session.expunge(binding)
                session.expunge(equipment)
                session.expunge(draft)
                return SensorConfigurationMutation(
                    equipment=equipment,
                    bindings=active,
                    draft=draft,
                )
        except IntegrityError as error:
            raise SensorBindingConflictError(
                "sensor configuration was concurrently changed by another operator"
            ) from error

    def _channels(
        self,
        session: Session,
        *,
        organization_id: str,
        node_id: str,
    ) -> list[ClimateChamberChannel]:
        bindings = list(
            session.scalars(
                select(EquipmentSensorBinding).where(
                    EquipmentSensorBinding.organization_id == organization_id,
                    EquipmentSensorBinding.node_id == node_id,
                    EquipmentSensorBinding.unbound_at.is_(None),
                )
            )
        )
        by_channel = {binding.channel_id: binding for binding in bindings}
        chamber, catalog_channels = (
            self._climate_catalog_repository.list_channels_for_node(
                node_id,
                organization_id=organization_id,
            )
        )
        if chamber is not None:
            channel_ids = [item.channel.channel_id for item in catalog_channels]
            latest_samples = self._latest_samples(
                session,
                node_id=node_id,
                channel_ids=channel_ids,
            )
            return [
                ClimateChamberChannel(
                    channel_id=item.channel.channel_id,
                    metric=item.channel.metric_type,
                    unit=item.channel.unit,
                    latest_value=(
                        latest_samples[item.channel.channel_id].value
                        if item.channel.channel_id in latest_samples
                        else None
                    ),
                    quality=(
                        latest_samples[item.channel.channel_id].quality
                        if item.channel.channel_id in latest_samples
                        else "no-data"
                    ),
                    captured_at=(
                        latest_samples[item.channel.channel_id].captured_at
                        if item.channel.channel_id in latest_samples
                        else item.channel.created_at
                    ),
                    binding=by_channel.get(item.channel.channel_id),
                )
                for item in catalog_channels
            ]

        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where(TelemetrySample.node_id == node_id)
                .order_by(
                    TelemetrySample.captured_at.desc(),
                    TelemetrySample.id.desc(),
                )
                .limit(5000)
            )
        )
        latest: dict[str, ClimateChamberChannel] = {}
        for sample in samples:
            if sample.channel_id in latest:
                continue
            latest[sample.channel_id] = ClimateChamberChannel(
                channel_id=sample.channel_id,
                metric=sample.metric,
                unit=sample.unit,
                latest_value=sample.value,
                quality=sample.quality,
                captured_at=sample.captured_at,
                binding=by_channel.get(sample.channel_id),
            )
        for binding in bindings:
            if binding.channel_id in latest:
                continue
            latest[binding.channel_id] = ClimateChamberChannel(
                channel_id=binding.channel_id,
                metric="temperature",
                unit="degC",
                latest_value=None,
                quality="no-data",
                captured_at=binding.bound_at,
                binding=binding,
            )
        return sorted(latest.values(), key=lambda item: item.channel_id)

    @staticmethod
    def _latest_samples(
        session: Session,
        *,
        node_id: str,
        channel_ids: list[str],
    ) -> dict[str, TelemetrySample]:
        if not channel_ids:
            return {}
        samples = list(
            session.scalars(
                select(TelemetrySample)
                .where(
                    TelemetrySample.node_id == node_id,
                    TelemetrySample.channel_id.in_(channel_ids),
                )
                .order_by(
                    TelemetrySample.captured_at.desc(),
                    TelemetrySample.id.desc(),
                )
                .limit(max(5000, len(channel_ids) * 4))
            )
        )
        latest: dict[str, TelemetrySample] = {}
        for sample in samples:
            latest.setdefault(sample.channel_id, sample)
        return latest

    def _climate_chamber(
        self,
        session: Session,
        organization_id: str,
        node_id: str,
    ) -> CentralNode:
        node = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == organization_id,
                CentralNode.node_id == node_id,
                CentralNode.state != NodeState.REVOKED.value,
            )
        )
        if node is None:
            raise ClimateChamberNotFoundError(
                f"climate chamber {node_id!r} was not found in this organization"
            )
        if self._climate_catalog_repository.has_catalog(
            organization_id=organization_id
        ):
            chamber, _ = self._climate_catalog_repository.list_channels_for_node(
                node_id,
                organization_id=organization_id,
            )
            if chamber is None:
                raise ClimateChamberNotFoundError(
                    f"node {node_id!r} is not an active climate chamber"
                )
        return node

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
    def _require_mutable(equipment: RefrigerationEquipmentRecord) -> None:
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
