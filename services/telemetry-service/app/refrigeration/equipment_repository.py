from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.climate_catalog.models import ClimateChamber, MeasurementBus
from app.db import Database
from app.nodes.domain import NodeState, normalize_node_id
from app.nodes.models import CentralNode
from app.refrigeration.models import (
    EquipmentSensorBinding,
    RefrigerationEquipmentRecord,
    RefrigerationLayoutDraft,
)
from app.refrigeration.schemas import RefrigerationEquipmentCreate, RefrigerationEquipmentUpdate
from app.security.repository import AuditEventInput, SecurityRepository


DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class EquipmentRepositoryError(RuntimeError):
    code = "equipment_repository_error"


class EquipmentNotFoundError(EquipmentRepositoryError):
    code = "equipment_not_found"


class EquipmentCodeConflictError(EquipmentRepositoryError):
    code = "equipment_code_conflict"


class EquipmentNodeNotFoundError(EquipmentRepositoryError):
    code = "equipment_node_not_found"


class EquipmentLifecycleConflictError(EquipmentRepositoryError):
    code = "equipment_lifecycle_conflict"


class EquipmentBindingConflictError(EquipmentRepositoryError):
    code = "equipment_binding_conflict"


class EquipmentVersionConflictError(EquipmentRepositoryError):
    code = "equipment_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"equipment version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


class PostgresRefrigerationEquipmentRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def list_active(
        self,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[RefrigerationEquipmentRecord]:
        with Session(self._engine, expire_on_commit=False) as session:
            items = list(
                session.scalars(
                    select(RefrigerationEquipmentRecord)
                    .where(
                        RefrigerationEquipmentRecord.organization_id == organization_id,
                        RefrigerationEquipmentRecord.deleted_at.is_(None),
                    )
                    .order_by(
                        RefrigerationEquipmentRecord.name.asc(),
                        RefrigerationEquipmentRecord.id.asc(),
                    )
                )
            )
            session.expunge_all()
            return items

    def get_active(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationEquipmentRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            item = session.scalar(
                select(RefrigerationEquipmentRecord).where(
                    RefrigerationEquipmentRecord.id == equipment_id,
                    RefrigerationEquipmentRecord.organization_id == organization_id,
                    RefrigerationEquipmentRecord.deleted_at.is_(None),
                )
            )
            if item is None:
                raise EquipmentNotFoundError(
                    f"equipment {equipment_id!r} was not found"
                )
            session.expunge(item)
            return item

    def create(
        self,
        payload: RefrigerationEquipmentCreate,
        *,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationEquipmentRecord:
        if payload.lifecycle_status == "retired":
            raise EquipmentLifecycleConflictError(
                "new equipment cannot be created as retired"
            )
        now = datetime.now(UTC)
        equipment_id = str(uuid4())
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    climate_chamber_id, node_id = self._validated_assignment(
                        session,
                        climate_chamber_id=payload.climate_chamber_id,
                        legacy_node_id=payload.node_id,
                        organization_id=organization_id,
                    )
                    record = RefrigerationEquipmentRecord(
                        id=equipment_id,
                        organization_id=organization_id,
                        code=payload.code,
                        name=payload.name,
                        location=payload.location,
                        laboratory=payload.laboratory,
                        zone=payload.zone,
                        climate_chamber_id=climate_chamber_id,
                        node_id=node_id,
                        equipment_type=payload.equipment_type,
                        manufacturer=payload.manufacturer,
                        model=payload.model,
                        serial_number=payload.serial_number,
                        temperature_class=payload.temperature_class,
                        installed_at=payload.installed_at,
                        serviced_at=payload.serviced_at,
                        lifecycle_status=payload.lifecycle_status,
                        status="offline",
                        average_temperature_c=0.0,
                        min_temperature_c=0.0,
                        max_temperature_c=0.0,
                        online_sensors=0,
                        total_sensors=payload.total_sensors,
                        active_alarms=0,
                        last_seen_at=None,
                        version=1,
                        created_by=actor_id.strip(),
                        created_at=now,
                        updated_at=now,
                        deleted_by=None,
                        deleted_at=None,
                    )
                    draft = RefrigerationLayoutDraft(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        equipment_id=equipment_id,
                        version=1,
                        image_id=None,
                        placements=[],
                        created_at=now,
                        updated_at=now,
                    )
                    session.add_all([record, draft])
                    session.flush()
                    if audit_repository is not None and audit_event is not None:
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=record.id,
                                before_snapshot=None,
                                after_snapshot=_equipment_snapshot(record),
                            ),
                            session=session,
                        )
                session.expunge(record)
                return record
        except IntegrityError as error:
            raise EquipmentCodeConflictError(
                f"equipment code {payload.code!r} already exists in this organization"
            ) from error

    def update(
        self,
        equipment_id: str,
        payload: RefrigerationEquipmentUpdate,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationEquipmentRecord:
        now = datetime.now(UTC)
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    record = self._locked_record(
                        session,
                        organization_id,
                        equipment_id,
                    )
                    self._check_version(record, expected_version)
                    if record.lifecycle_status == "retired":
                        raise EquipmentLifecycleConflictError(
                            "retired equipment is read-only"
                        )
                    active_bindings = list(
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
                    if payload.total_sensors < len(active_bindings):
                        raise EquipmentBindingConflictError(
                            "total_sensors cannot be lower than the active sensor binding count"
                        )
                    climate_chamber_id, node_id = self._validated_assignment(
                        session,
                        climate_chamber_id=payload.climate_chamber_id,
                        legacy_node_id=payload.node_id,
                        organization_id=organization_id,
                    )
                    if (
                        active_bindings
                        and climate_chamber_id != record.climate_chamber_id
                        and payload.lifecycle_status != "retired"
                    ):
                        raise EquipmentBindingConflictError(
                            "unbind active sensors before changing the climate chamber"
                        )
                    before = _equipment_snapshot(record)
                    retired_binding_ids: list[str] = []
                    if payload.lifecycle_status == "retired":
                        retired_binding_ids = self._end_bindings(
                            session,
                            active_bindings,
                            actor_id=actor_id,
                            now=now,
                        )
                        self._remove_binding_placements(
                            session,
                            organization_id=organization_id,
                            equipment_id=equipment_id,
                            sensor_ids={
                                binding.channel_id for binding in active_bindings
                            },
                            now=now,
                        )
                    record.code = payload.code
                    record.name = payload.name
                    record.location = payload.location
                    record.laboratory = payload.laboratory
                    record.zone = payload.zone
                    record.climate_chamber_id = climate_chamber_id
                    record.node_id = node_id
                    record.equipment_type = payload.equipment_type
                    record.manufacturer = payload.manufacturer
                    record.model = payload.model
                    record.serial_number = payload.serial_number
                    record.temperature_class = payload.temperature_class
                    record.installed_at = payload.installed_at
                    record.serviced_at = payload.serviced_at
                    record.lifecycle_status = payload.lifecycle_status
                    record.total_sensors = payload.total_sensors
                    if payload.lifecycle_status == "retired":
                        record.status = "offline"
                        record.online_sensors = 0
                        record.active_alarms = 0
                    record.updated_at = now
                    record.version += 1
                    session.flush()
                    if audit_repository is not None and audit_event is not None:
                        after = _equipment_snapshot(record)
                        if retired_binding_ids:
                            after["retired_sensor_binding_ids"] = retired_binding_ids
                        audit_repository.append_audit_event(
                            replace(
                                audit_event,
                                entity_id=record.id,
                                before_snapshot=before,
                                after_snapshot=after,
                            ),
                            session=session,
                        )
                session.expunge(record)
                return record
        except IntegrityError as error:
            raise EquipmentCodeConflictError(
                f"equipment code {payload.code!r} already exists in this organization"
            ) from error

    def soft_delete(
        self,
        equipment_id: str,
        *,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationEquipmentRecord:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                record = self._locked_record(
                    session,
                    organization_id,
                    equipment_id,
                )
                self._check_version(record, expected_version)
                active_bindings = list(
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
                before = _equipment_snapshot(record)
                ended = self._end_bindings(
                    session,
                    active_bindings,
                    actor_id=actor_id,
                    now=now,
                )
                self._remove_binding_placements(
                    session,
                    organization_id=organization_id,
                    equipment_id=equipment_id,
                    sensor_ids={binding.channel_id for binding in active_bindings},
                    now=now,
                )
                record.deleted_at = now
                record.deleted_by = actor_id.strip()
                record.lifecycle_status = "retired"
                record.status = "offline"
                record.online_sensors = 0
                record.active_alarms = 0
                record.updated_at = now
                record.version += 1
                if audit_repository is not None and audit_event is not None:
                    after = _equipment_snapshot(record)
                    if ended:
                        after["ended_sensor_binding_ids"] = ended
                    audit_repository.append_audit_event(
                        replace(
                            audit_event,
                            entity_id=record.id,
                            before_snapshot=before,
                            after_snapshot=after,
                        ),
                        session=session,
                    )
            session.expunge(record)
            return record

    @staticmethod
    def _validated_assignment(
        session: Session,
        *,
        climate_chamber_id: str | None,
        legacy_node_id: str | None,
        organization_id: str,
    ) -> tuple[str | None, str | None]:
        if climate_chamber_id is not None:
            normalized = climate_chamber_id.strip()
            chamber = session.scalar(
                select(ClimateChamber).where(
                    ClimateChamber.organization_id == organization_id,
                    or_(
                        ClimateChamber.id == normalized,
                        ClimateChamber.code == normalized.upper(),
                    ),
                    ClimateChamber.status == "active",
                )
            )
            if chamber is None:
                raise EquipmentNodeNotFoundError(
                    f"active climate chamber {normalized!r} was not found in this organization"
                )
            bus = session.scalar(
                select(MeasurementBus).where(
                    MeasurementBus.organization_id == organization_id,
                    MeasurementBus.id == chamber.bus_id,
                    MeasurementBus.status == "active",
                )
            )
            if bus is None:
                raise EquipmentNodeNotFoundError(
                    f"active measurement bus for climate chamber {normalized!r} was not found"
                )
            node = session.scalar(
                select(CentralNode).where(
                    CentralNode.organization_id == organization_id,
                    CentralNode.node_id == bus.node_id,
                    CentralNode.state != NodeState.REVOKED.value,
                )
            )
            if node is None:
                raise EquipmentNodeNotFoundError(
                    f"active node {bus.node_id!r} was not found in this organization"
                )
            return chamber.id, bus.node_id
        return None, PostgresRefrigerationEquipmentRepository._validated_node_id(
            session,
            legacy_node_id,
            organization_id=organization_id,
        )

    @staticmethod
    def _validated_node_id(
        session: Session,
        node_id: str | None,
        *,
        organization_id: str,
    ) -> str | None:
        if node_id is None:
            return None
        normalized = normalize_node_id(node_id)
        node = session.scalar(
            select(CentralNode).where(
                CentralNode.organization_id == organization_id,
                CentralNode.node_id == normalized,
            )
        )
        if node is None or node.state == NodeState.REVOKED.value:
            raise EquipmentNodeNotFoundError(
                f"active node {normalized!r} was not found in this organization"
            )
        return normalized

    @staticmethod
    def _locked_record(
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        record = session.scalar(
            select(RefrigerationEquipmentRecord)
            .where(
                RefrigerationEquipmentRecord.id == equipment_id,
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if record is None:
            raise EquipmentNotFoundError(
                f"equipment {equipment_id!r} was not found"
            )
        return record

    @staticmethod
    def _check_version(
        record: RefrigerationEquipmentRecord,
        expected_version: int,
    ) -> None:
        if record.version != expected_version:
            raise EquipmentVersionConflictError(
                expected_version=expected_version,
                actual_version=record.version,
            )

    @staticmethod
    def _end_bindings(
        session: Session,
        bindings: list[EquipmentSensorBinding],
        *,
        actor_id: str,
        now: datetime,
    ) -> list[str]:
        ended: list[str] = []
        for binding in bindings:
            binding.unbound_by = actor_id.strip()
            binding.unbound_at = now
            binding.version += 1
            ended.append(binding.id)
        if ended:
            session.flush()
        return ended

    @staticmethod
    def _remove_binding_placements(
        session: Session,
        *,
        organization_id: str,
        equipment_id: str,
        sensor_ids: set[str],
        now: datetime,
    ) -> None:
        if not sensor_ids:
            return
        draft = session.scalar(
            select(RefrigerationLayoutDraft)
            .where(
                RefrigerationLayoutDraft.organization_id == organization_id,
                RefrigerationLayoutDraft.equipment_id == equipment_id,
            )
            .with_for_update()
        )
        if draft is None:
            return
        remaining = [
            dict(item)
            for item in draft.placements
            if str(item.get("sensor_id")) not in sensor_ids
        ]
        if len(remaining) != len(draft.placements):
            draft.placements = remaining
            draft.version += 1
            draft.updated_at = now


def _equipment_snapshot(
    record: RefrigerationEquipmentRecord,
) -> dict[str, object]:
    return {
        "id": record.id,
        "organization_id": record.organization_id,
        "code": record.code,
        "name": record.name,
        "location": record.location,
        "laboratory": record.laboratory,
        "zone": record.zone,
        "climate_chamber_id": record.climate_chamber_id,
        "node_id": record.node_id,
        "equipment_type": record.equipment_type,
        "manufacturer": record.manufacturer,
        "model": record.model,
        "serial_number": record.serial_number,
        "temperature_class": record.temperature_class,
        "installed_at": record.installed_at.isoformat() if record.installed_at else None,
        "serviced_at": record.serviced_at.isoformat() if record.serviced_at else None,
        "lifecycle_status": record.lifecycle_status,
        "status": record.status,
        "total_sensors": record.total_sensors,
        "version": record.version,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "deleted_by": record.deleted_by,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
    }
