from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class EquipmentImage(Base):
    __tablename__ = "equipment_images"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_equipment_images_size_positive"),
        CheckConstraint("width_px > 0", name="ck_equipment_images_width_positive"),
        CheckConstraint("height_px > 0", name="ck_equipment_images_height_positive"),
        Index("ix_equipment_images_equipment_created", "equipment_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, nullable=False)
    height_px: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefrigerationLayoutDraft(Base):
    __tablename__ = "refrigeration_layout_drafts"
    __table_args__ = (
        UniqueConstraint("equipment_id", name="uq_refrigeration_layout_draft_equipment"),
        CheckConstraint("version >= 1", name="ck_refrigeration_layout_draft_version_positive"),
        Index("ix_refrigeration_layout_drafts_updated", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    image_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("equipment_images.id", name="fk_layout_draft_image_id", ondelete="RESTRICT"),
        nullable=True,
    )
    placements: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RefrigerationLayoutRevision(Base):
    __tablename__ = "refrigeration_layout_revisions"
    __table_args__ = (
        UniqueConstraint(
            "equipment_id", "revision", name="uq_refrigeration_layout_revision_equipment"
        ),
        CheckConstraint("revision >= 1", name="ck_refrigeration_layout_revision_positive"),
        CheckConstraint(
            "source_draft_version >= 1",
            name="ck_refrigeration_layout_revision_source_version_positive",
        ),
        Index(
            "ix_refrigeration_layout_revisions_equipment_published",
            "equipment_id",
            "published_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_draft_version: Mapped[int] = mapped_column(Integer, nullable=False)
    image_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("equipment_images.id", name="fk_layout_revision_image_id", ondelete="RESTRICT"),
        nullable=False,
    )
    placements: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
