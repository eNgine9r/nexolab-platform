from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.nodes.domain import NodeState
from app.nodes.models import CentralNode
from app.refrigeration.equipment_repository import (
    DEFAULT_ORGANIZATION_ID,
    EquipmentNotFoundError,
    EquipmentVersionConflictError,
)
from app.refrigeration.models import (
    EquipmentImage,
    EquipmentSensorBinding,
    RefrigerationEquipmentRecord,
    RefrigerationLayoutDraft,
)
from app.refrigeration.schemas import SensorBindingWrite
from app.security.repository import AuditEventInput, SecurityRepository


class EquipmentLifecycleRepositoryError(RuntimeError):
    code = "equipment_lifecycle_repository_error"


class EquipmentRetiredError(EquipmentLifecycleRepositoryError):
    code = "equipment_retired"


class EquipmentNodeRequiredError(EquipmentLifecycleRepositoryError):
    code = "equipment_node_required"


class EquipmentImageNotFoundError(EquipmentLifecycleRepositoryError):
    code = "equipment_image_not_found"


class EquipmentImageConflictError(EquipmentLifecycleRepositoryError):
    code = "equipment_image_conflict"


class SensorBindingNotFoundError(EquipmentLifecycleRepositoryError):
    code = "sensor_binding_not_found"


class SensorBindingConflictError(EquipmentLifecycleRepositoryError):
    code = "sensor_binding_conflict"


class SensorChannelNotFoundError(EquipmentLifecycleRepositoryError):
    code = "sensor_channel_not_found"


@dataclass(frozen=True, slots=True)
class AvailableSensor:
    channel_id: str
    metric: str
    unit: str
    latest_value: float | None
    quality: str
    captured_at: datetime
    binding: EquipmentSensorBinding | None


@dataclass(frozen=True, slots=True)
class SensorBindingMutation:
    equipment: RefrigerationEquipmentRecord
    binding: EquipmentSensorBinding | None
    draft: RefrigerationLayoutDraft


class PostgresEquipmentLifecycleRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_node_options(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[CentralNode]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(CentralNode)
                    .where(
                        CentralNode.organization_id == organization_id,
                        CentralNode.state != NodeState.REVOKED.value,
                    )
                    .order_by(CentralNode.display_name.asc(), CentralNode.node_id.asc())
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def list_images(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[EquipmentImage]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._equipment(session, organization_id, equipment_id)
            rows = list(
                session.scalars(
                    select(EquipmentImage)
                    .where(
                        EquipmentImage.organization_id == organization_id,
                        EquipmentImage.equipment_id == equipment_id,
                    )
                    .order_by(EquipmentImage.created_at.desc(), EquipmentImage.id.desc())
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def retire_image(
        self,
        equipment_id: str,
        image_id: str,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> tuple[RefrigerationEquipmentRecord, EquipmentImage]:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                equipment = self._locked_equipment(session, organization_id, equipment_id)
                self._check_version(equipment, expected_version)
                self._require_mutable(equipment)
                image = session.scalar(
                    select(EquipmentImage)
                    .where(
                        EquipmentImage.id == image_id,
                        EquipmentImage.organization_id == organization_id,
                        EquipmentImage.equipment_id == equipment_id,
                    )
                    .with_for_update()
                )
                if image is None:
                    raise EquipmentImageNotFoundError(f"image {image_id!r} was not found")
                if image.retired_at is not None:
                    raise EquipmentImageConflictError("equipment image is already retired")
                draft = self._locked_draft(session, organization_id, equipment_id)
                if draft.image_id == image_id:
                    raise EquipmentImageConflictError(
                        "replace the active draft image before retiring this image"
                    )

                before = _image_snapshot(image)
                image.retired_by = actor_id.strip()
                image.retired_at = now
                equipment.version += 1
                equipment.updated_at = now
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=before,
                    after=_image_snapshot(image),
                )
            session.expunge(image)
            session.expunge(equipment)
            return equipment, image

    def list_bindings(
        self,
        equipment_id: str,
        *,
        include_history: bool = False,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[EquipmentSensorBinding]:
        with Session(self._engine, expire_on_commit=False) as session:
            self._equipment(session, organization_id, equipment_id)
            statement = select(EquipmentSensorBinding).where(
                EquipmentSensorBinding.organization_id == organization_id,
                EquipmentSensorBinding.equipment_id == equipment_id,
            )
            if not include_history:
                statement = statement.where(EquipmentSensorBinding.unbound_at.is_(None))
            rows = list(
                session.scalars(
                    statement.order_by(
                        EquipmentSensorBinding.side.asc(),
                        EquipmentSensorBinding.shelf.asc(),
                        EquipmentSensorBinding.position.asc(),
                        EquipmentSensorBinding.bound_at.desc(),
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def list_available_sensors(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> tuple[str, list[AvailableSensor]]:
        with Session(self._engine, expire_on_commit=False) as session:
            equipment = self._equipment(session, organization_id, equipment_id)
            if equipment.node_id is None:
                raise EquipmentNodeRequiredError("assign a node before selecting sensors")
            self._node(session, organization_id, equipment.node_id)
            bindings = list(
                session.scalars(
                    select(EquipmentSensorBinding).where(
                        EquipmentSensorBinding.organization_id == organization_id,
                        EquipmentSensorBinding.node_id == equipment.node_id,
                        EquipmentSensorBinding.unbound_at.is_(None),
                    )
                )
            )
            by_channel = {binding.channel_id: binding for binding in bindings}
            samples = list(
                session.scalars(
                    select(TelemetrySample)
                    .where(TelemetrySample.node_id == equipment.node_id)
                    .order_by(TelemetrySample.captured_at.desc(), TelemetrySample.id.desc())
                    .limit(5000)
                )
            )
            latest: dict[str, AvailableSensor] = {}
            for sample in samples:
                if sample.channel_id in latest:
                    continue
                latest[sample.channel_id] = AvailableSensor(
                    channel_id=sample.channel_id,
                    metric=sample.metric,
                    unit=sample.unit,
                    latest_value=sample.value,
                    quality=sample.quality,
                    captured_at=sample.captured_at,
                    binding=by_channel.get(sample.channel_id),
                )
            return equipment.node_id, sorted(latest.values(), key=lambda item: item.channel_id)

    def bind_sensor(
        self,
        equipment_id: str,
        slot_key: str,
        payload: SensorBindingWrite,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> SensorBindingMutation:
        normalized_slot = _normalized_slot_key(slot_key)
        now = datetime.now(UTC)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    equipment = self._locked_equipment(session, organization_id, equipment_id)
                    self._check_version(equipment, expected_version)
                    self._require_mutable(equipment)
                    if equipment.node_id is None:
                        raise EquipmentNodeRequiredError("assign a node before binding sensors")
                    self._node(session, organization_id, equipment.node_id)
                    if not self._channel_exists(session, equipment.node_id, payload.channel_id):
                        raise SensorChannelNotFoundError(
                            f"channel {payload.channel_id!r} was not observed on node {equipment.node_id!r}"
                        )

                    current_slot = session.scalar(
                        select(EquipmentSensorBinding)
                        .where(
                            EquipmentSensorBinding.organization_id == organization_id,
                            EquipmentSensorBinding.equipment_id == equipment_id,
                            EquipmentSensorBinding.slot_key == normalized_slot,
                            EquipmentSensorBinding.unbound_at.is_(None),
                        )
                        .with_for_update()
                    )
                    current_channel = session.scalar(
                        select(EquipmentSensorBinding)
                        .where(
                            EquipmentSensorBinding.organization_id == organization_id,
                            EquipmentSensorBinding.node_id == equipment.node_id,
                            EquipmentSensorBinding.channel_id == payload.channel_id,
                            EquipmentSensorBinding.unbound_at.is_(None),
                        )
                        .with_for_update()
                    )
                    if current_channel is not None and (
                        current_slot is None or current_channel.id != current_slot.id
                    ):
                        raise SensorBindingConflictError(
                            f"channel {payload.channel_id!r} is already bound to "
                            f"{current_channel.equipment_id}:{current_channel.slot_key}"
                        )

                    draft = self._locked_draft(session, organization_id, equipment_id)
                    before = {
                        "equipment": _equipment_binding_snapshot(equipment),
                        "binding": _binding_snapshot(current_slot) if current_slot else None,
                        "draft_version": draft.version,
                    }
                    preserved_coordinates = _placement_coordinates(
                        draft.placements,
                        current_slot.channel_id if current_slot else payload.channel_id,
                    )
                    if current_slot is not None:
                        current_slot.unbound_by = actor_id.strip()
                        current_slot.unbound_at = now
                        current_slot.version += 1

                    binding = EquipmentSensorBinding(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        equipment_id=equipment_id,
                        node_id=equipment.node_id,
                        channel_id=payload.channel_id,
                        slot_key=normalized_slot,
                        label=payload.label,
                        side=payload.side,
                        shelf=payload.shelf,
                        position=payload.position,
                        version=1,
                        bound_by=actor_id.strip(),
                        bound_at=now,
                        unbound_by=None,
                        unbound_at=None,
                    )
                    session.add(binding)
                    draft.placements = _replace_placement(
                        draft.placements,
                        removed_sensor_id=current_slot.channel_id if current_slot else None,
                        sensor_id=payload.channel_id,
                        coordinates=preserved_coordinates
                        or _default_coordinates(payload.side, payload.shelf, payload.position),
                    )
                    draft.version += 1
                    draft.updated_at = now
                    equipment.version += 1
                    equipment.updated_at = now
                    session.flush()
                    self._append_audit(
                        session,
                        audit_repository,
                        audit_event,
                        before=before,
                        after={
                            "equipment": _equipment_binding_snapshot(equipment),
                            "binding": _binding_snapshot(binding),
                            "draft_version": draft.version,
                        },
                    )
                session.expunge(equipment)
                session.expunge(binding)
                session.expunge(draft)
                return SensorBindingMutation(equipment=equipment, binding=binding, draft=draft)
        except IntegrityError as error:
            raise SensorBindingConflictError(
                "sensor or equipment slot was concurrently bound by another operator"
            ) from error

    def unbind_sensor(
        self,
        equipment_id: str,
        slot_key: str,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> SensorBindingMutation:
        normalized_slot = _normalized_slot_key(slot_key)
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                equipment = self._locked_equipment(session, organization_id, equipment_id)
                self._check_version(equipment, expected_version)
                self._require_mutable(equipment)
                binding = session.scalar(
                    select(EquipmentSensorBinding)
                    .where(
                        EquipmentSensorBinding.organization_id == organization_id,
                        EquipmentSensorBinding.equipment_id == equipment_id,
                        EquipmentSensorBinding.slot_key == normalized_slot,
                        EquipmentSensorBinding.unbound_at.is_(None),
                    )
                    .with_for_update()
                )
                if binding is None:
                    raise SensorBindingNotFoundError(
                        f"active binding for slot {normalized_slot!r} was not found"
                    )
                draft = self._locked_draft(session, organization_id, equipment_id)
                before = {
                    "equipment": _equipment_binding_snapshot(equipment),
                    "binding": _binding_snapshot(binding),
                    "draft_version": draft.version,
                }
                binding.unbound_by = actor_id.strip()
                binding.unbound_at = now
                binding.version += 1
                draft.placements = [
                    dict(item)
                    for item in draft.placements
                    if str(item.get("sensor_id")) != binding.channel_id
                ]
                draft.version += 1
                draft.updated_at = now
                equipment.version += 1
                equipment.updated_at = now
                session.flush()
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=before,
                    after={
                        "equipment": _equipment_binding_snapshot(equipment),
                        "binding": _binding_snapshot(binding),
                        "draft_version": draft.version,
                    },
                )
            session.expunge(equipment)
            session.expunge(draft)
            return SensorBindingMutation(equipment=equipment, binding=None, draft=draft)

    @staticmethod
    def _equipment(
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        equipment = session.scalar(
            select(RefrigerationEquipmentRecord).where(
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.id == equipment_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
            )
        )
        if equipment is None:
            raise EquipmentNotFoundError(f"equipment {equipment_id!r} was not found")
        return equipment

    @classmethod
    def _locked_equipment(
        cls,
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
            raise EquipmentNotFoundError(f"equipment {equipment_id!r} was not found")
        return equipment

    @staticmethod
    def _node(session: Session, organization_id: str, node_id: str) -> CentralNode:
        node = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == organization_id,
                CentralNode.node_id == node_id,
                CentralNode.state != NodeState.REVOKED.value,
            )
        )
        if node is None:
            raise EquipmentNodeRequiredError(
                f"node {node_id!r} is unavailable in this organization"
            )
        return node

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
            raise EquipmentLifecycleRepositoryError("equipment layout draft was not found")
        return draft

    @staticmethod
    def _channel_exists(session: Session, node_id: str, channel_id: str) -> bool:
        return (
            session.scalar(
                select(TelemetrySample.id)
                .where(
                    TelemetrySample.node_id == node_id,
                    TelemetrySample.channel_id == channel_id,
                )
                .limit(1)
            )
            is not None
        )

    @staticmethod
    def _check_version(equipment: RefrigerationEquipmentRecord, expected_version: int) -> None:
        if equipment.version != expected_version:
            raise EquipmentVersionConflictError(
                expected_version=expected_version,
                actual_version=equipment.version,
            )

    @staticmethod
    def _require_mutable(equipment: RefrigerationEquipmentRecord) -> None:
        if equipment.lifecycle_status == "retired":
            raise EquipmentRetiredError("retired equipment is read-only")

    @staticmethod
    def _append_audit(
        session: Session,
        repository: SecurityRepository | None,
        event: AuditEventInput | None,
        *,
        before: dict[str, object] | None,
        after: dict[str, object],
    ) -> None:
        if repository is None or event is None:
            return
        repository.append_audit_event(
            replace(event, before_snapshot=before, after_snapshot=after),
            session=session,
        )


def _normalized_slot_key(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 32:
        raise SensorBindingConflictError("slot_key must contain 1..32 characters")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in normalized):
        raise SensorBindingConflictError(
            "slot_key may contain only lowercase letters, digits, hyphens and underscores"
        )
    return normalized


def _default_coordinates(side: str, shelf: int, position: int) -> tuple[float, float]:
    x = 0.17 + (position - 1) * 0.13 + (0.032 if side == "rear" else -0.032)
    y = 0.21 + (shelf - 1) * 0.205 + (0.055 if side == "rear" else 0.0)
    return min(0.94, max(0.06, x)), min(0.91, max(0.08, y))


def _placement_coordinates(
    placements: list[dict[str, object]],
    sensor_id: str,
) -> tuple[float, float] | None:
    for item in placements:
        if str(item.get("sensor_id")) == sensor_id:
            return float(item["x"]), float(item["y"])
    return None


def _replace_placement(
    placements: list[dict[str, object]],
    *,
    removed_sensor_id: str | None,
    sensor_id: str,
    coordinates: tuple[float, float],
) -> list[dict[str, object]]:
    removed = {sensor_id}
    if removed_sensor_id is not None:
        removed.add(removed_sensor_id)
    remaining = [
        dict(item)
        for item in placements
        if str(item.get("sensor_id")) not in removed
    ]
    remaining.append({"sensor_id": sensor_id, "x": coordinates[0], "y": coordinates[1]})
    return remaining


def _equipment_binding_snapshot(record: RefrigerationEquipmentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "node_id": record.node_id,
        "lifecycle_status": record.lifecycle_status,
        "version": record.version,
    }


def _binding_snapshot(binding: EquipmentSensorBinding) -> dict[str, object]:
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
        "unbound_at": binding.unbound_at.isoformat() if binding.unbound_at else None,
    }


def _image_snapshot(image: EquipmentImage) -> dict[str, object]:
    return {
        "id": image.id,
        "equipment_id": image.equipment_id,
        "original_filename": image.original_filename,
        "checksum_sha256": image.checksum_sha256,
        "created_by": image.created_by,
        "created_at": image.created_at.isoformat(),
        "retired_by": image.retired_by,
        "retired_at": image.retired_at.isoformat() if image.retired_at else None,
    }
