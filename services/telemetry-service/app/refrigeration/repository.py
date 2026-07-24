from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.refrigeration.models import (
    EquipmentImage,
    RefrigerationLayoutDraft,
    RefrigerationLayoutRevision,
)
from app.refrigeration.schemas import SensorPlacementPayload


class LayoutRepositoryError(RuntimeError):
    code = "layout_repository_error"


class LayoutNotFoundError(LayoutRepositoryError):
    code = "layout_not_found"


class LayoutImageNotFoundError(LayoutRepositoryError):
    code = "layout_image_not_found"


class LayoutRevisionNotFoundError(LayoutRepositoryError):
    code = "layout_revision_not_found"


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

    def get_or_create_draft(self, equipment_id: str) -> RefrigerationLayoutDraft:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                draft = session.scalar(
                    select(RefrigerationLayoutDraft)
                    .where(RefrigerationLayoutDraft.equipment_id == equipment_id)
                    .with_for_update()
                )
                if draft is None:
                    now = datetime.now(UTC)
                    draft = RefrigerationLayoutDraft(
                        id=str(uuid4()),
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

    def get_draft(self, equipment_id: str) -> RefrigerationLayoutDraft:
        with Session(self._engine, expire_on_commit=False) as session:
            draft = session.scalar(
                select(RefrigerationLayoutDraft).where(
                    RefrigerationLayoutDraft.equipment_id == equipment_id
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
    ) -> RefrigerationLayoutDraft:
        normalized = _validated_placements(placements, require_non_empty=False)
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                draft = self._locked_draft(session, equipment_id)
                self._check_version(draft, expected_version)
                if image_id is not None:
                    self._require_image(session, equipment_id, image_id)
                draft.image_id = image_id
                draft.placements = normalized
                draft.version += 1
                draft.updated_at = now
            session.expunge(draft)
            return draft

    def publish(
        self,
        *,
        equipment_id: str,
        expected_version: int,
        actor_id: str,
    ) -> PublishedLayoutResult:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                draft = self._locked_draft(session, equipment_id)
                self._check_version(draft, expected_version)
                placements = _validated_raw_placements(draft.placements, require_non_empty=True)
                if draft.image_id is None:
                    raise LayoutValidationError(["image_required"])
                self._require_image(session, equipment_id, draft.image_id)
                next_revision = int(
                    session.scalar(
                        select(func.max(RefrigerationLayoutRevision.revision)).where(
                            RefrigerationLayoutRevision.equipment_id == equipment_id
                        )
                    )
                    or 0
                ) + 1
                revision = RefrigerationLayoutRevision(
                    id=str(uuid4()),
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
            session.expunge(draft)
            session.expunge(revision)
            return PublishedLayoutResult(draft=draft, published=revision)

    def get_published(self, equipment_id: str) -> RefrigerationLayoutRevision | None:
        with Session(self._engine, expire_on_commit=False) as session:
            revision = session.scalar(
                select(RefrigerationLayoutRevision)
                .where(RefrigerationLayoutRevision.equipment_id == equipment_id)
                .order_by(RefrigerationLayoutRevision.revision.desc())
                .limit(1)
            )
            if revision is not None:
                session.expunge(revision)
            return revision

    def list_history(self, equipment_id: str) -> list[RefrigerationLayoutRevision]:
        with Session(self._engine, expire_on_commit=False) as session:
            items = list(
                session.scalars(
                    select(RefrigerationLayoutRevision)
                    .where(RefrigerationLayoutRevision.equipment_id == equipment_id)
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
    ) -> RefrigerationLayoutDraft:
        now = datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                draft = self._locked_draft(session, equipment_id)
                self._check_version(draft, expected_version)
                revision = session.scalar(
                    select(RefrigerationLayoutRevision).where(
                        RefrigerationLayoutRevision.id == revision_id,
                        RefrigerationLayoutRevision.equipment_id == equipment_id,
                    )
                )
                if revision is None:
                    raise LayoutRevisionNotFoundError(
                        f"layout revision {revision_id!r} was not found"
                    )
                draft.image_id = revision.image_id
                draft.placements = [dict(item) for item in revision.placements]
                draft.version += 1
                draft.updated_at = now
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
    ) -> EquipmentImage:
        record = EquipmentImage(
            id=image_id,
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
        )
        with Session(self._engine, expire_on_commit=False) as session:
            session.add(record)
            session.commit()
            session.expunge(record)
        return record

    def get_image(self, equipment_id: str, image_id: str) -> EquipmentImage:
        with Session(self._engine, expire_on_commit=False) as session:
            image = session.scalar(
                select(EquipmentImage).where(
                    EquipmentImage.id == image_id,
                    EquipmentImage.equipment_id == equipment_id,
                )
            )
            if image is None:
                raise LayoutImageNotFoundError(f"image {image_id!r} was not found")
            session.expunge(image)
            return image

    def _locked_draft(self, session: Session, equipment_id: str) -> RefrigerationLayoutDraft:
        draft = session.scalar(
            select(RefrigerationLayoutDraft)
            .where(RefrigerationLayoutDraft.equipment_id == equipment_id)
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
    def _require_image(session: Session, equipment_id: str, image_id: str) -> EquipmentImage:
        image = session.scalar(
            select(EquipmentImage).where(
                EquipmentImage.id == image_id,
                EquipmentImage.equipment_id == equipment_id,
            )
        )
        if image is None:
            raise LayoutImageNotFoundError(f"image {image_id!r} was not found")
        return image


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
