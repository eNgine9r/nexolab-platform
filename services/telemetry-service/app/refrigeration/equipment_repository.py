from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Database
from app.refrigeration.models import RefrigerationEquipmentRecord, RefrigerationLayoutDraft
from app.refrigeration.schemas import RefrigerationEquipmentCreate
from app.security.repository import AuditEventInput, SecurityRepository

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class EquipmentRepositoryError(RuntimeError):
    code = "equipment_repository_error"


class EquipmentNotFoundError(EquipmentRepositoryError):
    code = "equipment_not_found"


class EquipmentCodeConflictError(EquipmentRepositoryError):
    code = "equipment_code_conflict"


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
            for item in items:
                session.expunge(item)
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
                raise EquipmentNotFoundError(f"equipment {equipment_id!r} was not found")
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
        now = datetime.now(UTC)
        equipment_id = str(uuid4())
        record = RefrigerationEquipmentRecord(
            id=equipment_id,
            organization_id=organization_id,
            code=payload.code,
            name=payload.name,
            location=payload.location,
            equipment_type=payload.equipment_type,
            manufacturer=payload.manufacturer,
            model=payload.model,
            serial_number=payload.serial_number,
            temperature_class=payload.temperature_class,
            installed_at=payload.installed_at,
            serviced_at=payload.serviced_at,
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

        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    session.add(record)
                    session.add(draft)
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
                    raise EquipmentNotFoundError(f"equipment {equipment_id!r} was not found")
                if record.version != expected_version:
                    raise EquipmentVersionConflictError(
                        expected_version=expected_version,
                        actual_version=record.version,
                    )
                before = _equipment_snapshot(record)
                record.deleted_at = now
                record.deleted_by = actor_id.strip()
                record.updated_at = now
                record.version += 1
                if audit_repository is not None and audit_event is not None:
                    audit_repository.append_audit_event(
                        replace(
                            audit_event,
                            entity_id=record.id,
                            before_snapshot=before,
                            after_snapshot=_equipment_snapshot(record),
                        ),
                        session=session,
                    )
            session.expunge(record)
            return record


def _equipment_snapshot(record: RefrigerationEquipmentRecord) -> dict[str, object]:
    return {
        "id": record.id,
        "organization_id": record.organization_id,
        "code": record.code,
        "name": record.name,
        "location": record.location,
        "equipment_type": record.equipment_type,
        "manufacturer": record.manufacturer,
        "model": record.model,
        "serial_number": record.serial_number,
        "temperature_class": record.temperature_class,
        "installed_at": record.installed_at.isoformat() if record.installed_at else None,
        "serviced_at": record.serviced_at.isoformat() if record.serviced_at else None,
        "status": record.status,
        "total_sensors": record.total_sensors,
        "version": record.version,
        "created_by": record.created_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "deleted_by": record.deleted_by,
        "deleted_at": record.deleted_at.isoformat() if record.deleted_at else None,
    }
