from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
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


class RefrigerationEquipmentRecord(Base):
    __tablename__ = "refrigeration_equipment"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name="uq_refrigeration_equipment_organization_code",
        ),
        CheckConstraint(
            "status IN ('normal', 'warning', 'alarm', 'offline')",
            name="ck_refrigeration_equipment_status",
        ),
        CheckConstraint("version >= 1", name="ck_refrigeration_equipment_version_positive"),
        CheckConstraint("online_sensors >= 0", name="ck_refrigeration_equipment_online_non_negative"),
        CheckConstraint("total_sensors >= 0", name="ck_refrigeration_equipment_total_non_negative"),
        CheckConstraint("online_sensors <= total_sensors", name="ck_refrigeration_equipment_online_within_total"),
        CheckConstraint("active_alarms >= 0", name="ck_refrigeration_equipment_alarms_non_negative"),
        Index(
            "ix_refrigeration_equipment_active",
            "organization_id",
            "deleted_at",
            "status",
            "name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_refrigeration_equipment_organization",
            ondelete="RESTRICT",
        ),
        primary_key=True,
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    location: Mapped[str] = mapped_column(String(255), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(128), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(128), nullable=False)
    temperature_class: Mapped[str] = mapped_column(String(128), nullable=False)
    installed_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    serviced_at: Mapped[date | None] = mapped_column(Date(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline", server_default="offline")
    average_temperature_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    min_temperature_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    max_temperature_c: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default=text("0"))
    online_sensors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    total_sensors: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    active_alarms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EquipmentImage(Base):
    __tablename__ = "equipment_images"
    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="ck_equipment_images_size_positive"),
        CheckConstraint("width_px > 0", name="ck_equipment_images_width_positive"),
        CheckConstraint("height_px > 0", name="ck_equipment_images_height_positive"),
        Index(
            "ix_equipment_images_equipment_created",
            "organization_id",
            "equipment_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_equipment_images_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
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
        UniqueConstraint(
            "organization_id",
            "equipment_id",
            name="uq_refrigeration_layout_draft_equipment",
        ),
        CheckConstraint("version >= 1", name="ck_refrigeration_layout_draft_version_positive"),
        Index(
            "ix_refrigeration_layout_drafts_updated",
            "organization_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_refrigeration_layout_draft_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
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
            "organization_id",
            "equipment_id",
            "revision",
            name="uq_refrigeration_layout_revision_equipment",
        ),
        CheckConstraint("revision >= 1", name="ck_refrigeration_layout_revision_positive"),
        CheckConstraint(
            "source_draft_version >= 1",
            name="ck_refrigeration_layout_revision_source_version_positive",
        ),
        Index(
            "ix_refrigeration_layout_revisions_equipment_published",
            "organization_id",
            "equipment_id",
            "published_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_refrigeration_layout_revision_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
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
