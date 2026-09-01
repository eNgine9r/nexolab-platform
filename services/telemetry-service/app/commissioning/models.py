from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


_LIFECYCLES = "'draft', 'ready_for_preflight', 'blocked', 'unsupported', 'cancelled'"


class EquipmentCommissioningSession(Base):
    __tablename__ = "equipment_commissioning_sessions"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "create_idempotency_key",
            name="uq_equipment_commissioning_session_create_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "target_equipment_key"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_equipment_commissioning_session_target_equipment",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"lifecycle IN ({_LIFECYCLES})",
            name="ck_equipment_commissioning_session_lifecycle",
        ),
        CheckConstraint("version >= 1", name="ck_equipment_commissioning_session_version"),
        CheckConstraint(
            "unit_id IS NULL OR (unit_id BETWEEN 1 AND 247)",
            name="ck_equipment_commissioning_session_unit_id",
        ),
        Index(
            "ix_equipment_commissioning_session_organization_updated",
            "organization_id",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_equipment_commissioning_session_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    create_idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    create_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", server_default="draft")
    device_class: Mapped[str] = mapped_column(String(64), nullable=False)
    manufacturer: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transport_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bus_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stable_transport_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    target_equipment_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    unsupported_reason: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
