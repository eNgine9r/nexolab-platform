from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.refrigeration.models import (
    EquipmentImage,
    RefrigerationEquipmentRecord,
    RefrigerationLayoutDraft,
    RefrigerationLayoutRevision,
)
from app.refrigeration.schemas import SensorPlacementPayload
from app.security.repository import AuditEventInput, SecurityRepository

DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


class LayoutRepositoryError(RuntimeError):
    code = "layout_repository_error"


class LayoutNotFoundError(LayoutRepositoryError):
    code = "layout_not_found"


class LayoutImageNotFoundError(LayoutRepositoryError):
    code = "layout_image_not_found"


class LayoutRevisionNotFoundError(LayoutRepositoryError):
    code = "layout_revision_not_found"


class LayoutEquipmentRetiredError(LayoutRepositoryError):
    code = "equipment_retired"


class LayoutValidationError(LayoutRepositoryError):
    code = "layout_validation_failed"

    def __init__(self, issues: list[str]) -> None:
        super().__init__("layout validation failed")
        self.issues = issues


class LayoutVersionConflictError(LayoutRepositoryError):
    code = "layout_version_conflict"

    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"layout version conflict: expected {expected_version}, actual {actual_version}"
        )
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclass(frozen=True, slots=True)
class PublishedLayoutResult:
    draft: RefrigerationLayoutDraft
    published: RefrigerationLayoutRevision


class PostgresRefrigerationLayoutRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def get_or_create_draft(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationLayoutDraft:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._ensure_equipment_record(session, organization_id, equipment_id)
                draft = session.scalar(
                    select(RefrigerationLayoutDraft)
                    .where(
                        RefrigerationLayoutDraft.organization_id == organization_id,
                        RefrigerationLayoutDraft.equipment_id == equipment_id,
                    )
                    .with_for_update()
                )
                if draft is None:
                    now = datetime.now(UTC)
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
                    session.add(draft)
            session.expunge(draft)
            return draft

    def get_draft(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationLayoutDraft:
        with Session(self._engine, expire_on_commit=False) as session:
            draft = session.scalar(
                select(RefrigerationLayoutDraft).where(
                    RefrigerationLayoutDraft.organization_id == organization_id,
                    RefrigerationLayoutDraft.equipment_id == equipment_id,
                )
            )
            if draft is None:
                raise LayoutNotFoundError(f"layout draft for {equipment_id!r} was not found")
            session.expunge(draft)
            return draft

    def save_draft(
        self,
        *,
        equipment_id: str,
        expected_version: int,
        image_id: str | None,
        placements: Iterable[SensorPlacementPayload | dict[str, Any]],
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationLayoutDraft:
        normalized = _validated_placements(placements, require_non_empty=False)
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._require_mutable_equipment(session, organization_id, equipment_id)
                draft = self._locked_draft(session, organization_id, equipment_id)
                self._check_version(draft, expected_version)
                before = _draft_snapshot(draft)
                if image_id is not None:
                    self._require_image(
                        session,
                        organization_id,
                        equipment_id,
                        image_id,
                        active_only=True,
                    )
                draft.image_id = image_id
                draft.placements = normalized
                draft.version += 1
                draft.updated_at = now
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=before,
                    after=_draft_snapshot(draft),
                )
            session.expunge(draft)
            return draft

    def publish(
        self,
        *,
        equipment_id: str,
        expected_version: int,
        actor_id: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> PublishedLayoutResult:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._require_mutable_equipment(session, organization_id, equipment_id)
                draft = self._locked_draft(session, organization_id, equipment_id)
                self._check_version(draft, expected_version)
                before = _draft_snapshot(draft)
                placements = _validated_raw_placements(draft.placements, require_non_empty=True)
                if draft.image_id is None:
                    raise LayoutValidationError(["image_required"])
                self._require_image(
                    session,
                    organization_id,
                    equipment_id,
                    draft.image_id,
                    active_only=True,
                )
                next_revision = int(
                    session.scalar(
                        select(func.max(RefrigerationLayoutRevision.revision)).where(
                            RefrigerationLayoutRevision.organization_id == organization_id,
                            RefrigerationLayoutRevision.equipment_id == equipment_id,
                        )
                    )
                    or 0
                ) + 1
                revision = RefrigerationLayoutRevision(
                    id=str(uuid4()),
                    organization_id=organization_id,
                    equipment_id=equipment_id,
                    revision=next_revision,
                    source_draft_version=draft.version,
                    image_id=draft.image_id,
                    placements=placements,
                    published_by=actor_id.strip(),
                    published_at=now,
                )
                session.add(revision)
                draft.version += 1
                draft.updated_at = now
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=before,
                    after={
                        "draft": _draft_snapshot(draft),
                        "published": _revision_snapshot(revision),
                    },
                )
            session.expunge(draft)
            session.expunge(revision)
            return PublishedLayoutResult(draft=draft, published=revision)

    def get_published(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> RefrigerationLayoutRevision | None:
        with Session(self._engine, expire_on_commit=False) as session:
            revision = session.scalar(
                select(RefrigerationLayoutRevision)
                .where(
                    RefrigerationLayoutRevision.organization_id == organization_id,
                    RefrigerationLayoutRevision.equipment_id == equipment_id,
                )
                .order_by(RefrigerationLayoutRevision.revision.desc())
                .limit(1)
            )
            if revision is not None:
                session.expunge(revision)
            return revision

    def list_history(
        self,
        equipment_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> list[RefrigerationLayoutRevision]:
        with Session(self._engine, expire_on_commit=False) as session:
            items = list(
                session.scalars(
                    select(RefrigerationLayoutRevision)
                    .where(
                        RefrigerationLayoutRevision.organization_id == organization_id,
                        RefrigerationLayoutRevision.equipment_id == equipment_id,
                    )
                    .order_by(RefrigerationLayoutRevision.revision.desc())
                )
            )
            for item in items:
                session.expunge(item)
            return items

    def restore(
        self,
        *,
        equipment_id: str,
        revision_id: str,
        expected_version: int,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> RefrigerationLayoutDraft:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._require_mutable_equipment(session, organization_id, equipment_id)
                draft = self._locked_draft(session, organization_id, equipment_id)
                self._check_version(draft, expected_version)
                before = _draft_snapshot(draft)
                revision = session.scalar(
                    select(RefrigerationLayoutRevision).where(
                        RefrigerationLayoutRevision.id == revision_id,
                        RefrigerationLayoutRevision.organization_id == organization_id,
                        RefrigerationLayoutRevision.equipment_id == equipment_id,
                    )
                )
                if revision is None:
                    raise LayoutRevisionNotFoundError(
                        f"layout revision {revision_id!r} was not found"
                    )
                self._require_image(
                    session,
                    organization_id,
                    equipment_id,
                    revision.image_id,
                    active_only=False,
                )
                draft.image_id = revision.image_id
                draft.placements = [dict(item) for item in revision.placements]
                draft.version += 1
                draft.updated_at = now
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=before,
                    after={
                        **_draft_snapshot(draft),
                        "restored_revision_id": revision.id,
                        "restored_revision": revision.revision,
                    },
                )
            session.expunge(draft)
            return draft

    def create_image(
        self,
        *,
        image_id: str,
        equipment_id: str,
        storage_key: str,
        original_filename: str,
        media_type: str,
        size_bytes: int,
        width_px: int,
        height_px: int,
        checksum_sha256: str,
        object_etag: str | None,
        created_by: str,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
        audit_repository: SecurityRepository | None = None,
        audit_event: AuditEventInput | None = None,
    ) -> EquipmentImage:
        record = EquipmentImage(
            id=image_id,
            organization_id=organization_id,
            equipment_id=equipment_id,
            storage_key=storage_key,
            original_filename=original_filename,
            media_type=media_type,
            size_bytes=size_bytes,
            width_px=width_px,
            height_px=height_px,
            checksum_sha256=checksum_sha256,
            object_etag=object_etag,
            created_by=created_by.strip(),
            created_at=datetime.now(UTC),
            retired_by=None,
            retired_at=None,
        )
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                self._require_mutable_equipment(session, organization_id, equipment_id)
                session.add(record)
                self._append_audit(
                    session,
                    audit_repository,
                    audit_event,
                    before=None,
                    after=_image_snapshot(record),
                )
            session.expunge(record)
        return record

    def get_image(
        self,
        equipment_id: str,
        image_id: str,
        *,
        organization_id: str = DEFAULT_ORGANIZATION_ID,
    ) -> EquipmentImage:
        with Session(self._engine, expire_on_commit=False) as session:
            image = session.scalar(
                select(EquipmentImage).where(
                    EquipmentImage.id == image_id,
                    EquipmentImage.organization_id == organization_id,
                    EquipmentImage.equipment_id == equipment_id,
                )
            )
            if image is None:
                raise LayoutImageNotFoundError(f"image {image_id!r} was not found")
            session.expunge(image)
            return image

    @staticmethod
    def _ensure_equipment_record(
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        equipment = session.scalar(
            select(RefrigerationEquipmentRecord)
            .where(
                RefrigerationEquipmentRecord.organization_id == organization_id,
                RefrigerationEquipmentRecord.id == equipment_id,
            )
            .with_for_update()
        )
        if equipment is not None:
            return equipment

        now = datetime.now(UTC)
        legacy_code = f"LEGACY-{equipment_id}"[:128]
        equipment = RefrigerationEquipmentRecord(
            id=equipment_id,
            organization_id=organization_id,
            code=legacy_code,
            name=f"Legacy equipment {equipment_id}"[:255],
            location="Legacy layout",
            laboratory=None,
            zone=None,
            node_id=None,
            equipment_type="Refrigeration equipment",
            manufacturer="Unknown",
            model="Unknown",
            serial_number=legacy_code,
            temperature_class="Unknown",
            installed_at=None,
            serviced_at=None,
            lifecycle_status="active",
            status="offline",
            average_temperature_c=0.0,
            min_temperature_c=0.0,
            max_temperature_c=0.0,
            online_sensors=0,
            total_sensors=0,
            active_alarms=0,
            last_seen_at=None,
            version=1,
            created_by="layout-compatibility",
            created_at=now,
            updated_at=now,
            deleted_by=None,
            deleted_at=None,
        )
        session.add(equipment)
        session.flush()
        return equipment

    @classmethod
    def _require_mutable_equipment(
        cls,
        session: Session,
        organization_id: str,
        equipment_id: str,
    ) -> RefrigerationEquipmentRecord:
        equipment = cls._ensure_equipment_record(session, organization_id, equipment_id)
        if equipment.deleted_at is not None:
            raise LayoutEquipmentRetiredError("deleted equipment layout is read-only")
        if equipment.lifecycle_status == "retired":
            raise LayoutEquipmentRetiredError("retired equipment layout is read-only")
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
            raise LayoutNotFoundError(f"layout draft for {equipment_id!r} was not found")
        return draft

    @staticmethod
    def _check_version(draft: RefrigerationLayoutDraft, expected_version: int) -> None:
        if draft.version != expected_version:
            raise LayoutVersionConflictError(
                expected_version=expected_version,
                actual_version=draft.version,
            )

    @staticmethod
    def _require_image(
        session: Session,
        organization_id: str,
        equipment_id: str,
        image_id: str,
        *,
        active_only: bool,
    ) -> EquipmentImage:
        statement = select(EquipmentImage).where(
            EquipmentImage.id == image_id,
            EquipmentImage.organization_id == organization_id,
            EquipmentImage.equipment_id == equipment_id,
        )
        if active_only:
            statement = statement.where(EquipmentImage.retired_at.is_(None))
        image = session.scalar(statement)
        if image is None:
            raise LayoutImageNotFoundError(f"active image {image_id!r} was not found")
        return image

    @staticmethod
    def _append_audit(
        session: Session,
        audit_repository: SecurityRepository | None,
        audit_event: AuditEventInput | None,
        *,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        if audit_repository is None or audit_event is None:
            return
        audit_repository.append_audit_event(
            replace(
                audit_event,
                before_snapshot=before,
                after_snapshot=after,
            ),
            session=session,
        )


def _draft_snapshot(draft: RefrigerationLayoutDraft) -> dict[str, Any]:
    return {
        "id": draft.id,
        "organization_id": draft.organization_id,
        "equipment_id": draft.equipment_id,
        "version": draft.version,
        "image_id": draft.image_id,
        "placements": [dict(item) for item in draft.placements],
        "updated_at": draft.updated_at.isoformat(),
    }


def _revision_snapshot(revision: RefrigerationLayoutRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "organization_id": revision.organization_id,
        "equipment_id": revision.equipment_id,
        "revision": revision.revision,
        "source_draft_version": revision.source_draft_version,
        "image_id": revision.image_id,
        "placements": [dict(item) for item in revision.placements],
        "published_by": revision.published_by,
        "published_at": revision.published_at.isoformat(),
    }


def _image_snapshot(image: EquipmentImage) -> dict[str, Any]:
    return {
        "id": image.id,
        "organization_id": image.organization_id,
        "equipment_id": image.equipment_id,
        "original_filename": image.original_filename,
        "media_type": image.media_type,
        "size_bytes": image.size_bytes,
        "width_px": image.width_px,
        "height_px": image.height_px,
        "checksum_sha256": image.checksum_sha256,
        "created_by": image.created_by,
        "created_at": image.created_at.isoformat(),
        "retired_by": image.retired_by,
        "retired_at": image.retired_at.isoformat() if image.retired_at else None,
    }


def _validated_placements(
    placements: Iterable[SensorPlacementPayload | dict[str, Any]], *, require_non_empty: bool
) -> list[dict[str, Any]]:
    return _validated_raw_placements(
        [
            placement.model_dump() if isinstance(placement, SensorPlacementPayload) else dict(placement)
            for placement in placements
        ],
        require_non_empty=require_non_empty,
    )


def _validated_raw_placements(
    placements: Iterable[dict[str, Any]], *, require_non_empty: bool
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    issues: list[str] = []
    seen: set[str] = set()
    for raw in placements:
        try:
            placement = SensorPlacementPayload.model_validate(raw)
        except Exception:
            issues.append("invalid_placement")
            continue
        if placement.sensor_id in seen:
            issues.append(f"duplicate_sensor:{placement.sensor_id}")
        seen.add(placement.sensor_id)
        normalized.append(placement.model_dump())
    if require_non_empty and not normalized:
        issues.append("placements_required")
    if issues:
        raise LayoutValidationError(issues)
    return normalized
