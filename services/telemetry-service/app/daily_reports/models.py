from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
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

REPORT_STATUSES = ("normal", "attention", "critical", "incomplete")
_REPORT_STATUS_SQL = ", ".join(f"'{value}'" for value in REPORT_STATUSES)


class RefrigerationDailyReportProfile(Base):
    __tablename__ = "refrigeration_daily_report_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_daily_report_profiles_organization_id",
        ),
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_daily_report_profiles_organization_name",
        ),
        ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_daily_report_profiles_equipment",
            ondelete="RESTRICT",
        ),
        CheckConstraint("version >= 1", name="ck_daily_report_profiles_version_positive"),
        CheckConstraint(
            "report_hour BETWEEN 0 AND 23",
            name="ck_daily_report_profiles_hour",
        ),
        CheckConstraint(
            "report_minute BETWEEN 0 AND 59",
            name="ck_daily_report_profiles_minute",
        ),
        CheckConstraint(
            "analysis_window_minutes BETWEEN 1 AND 10080",
            name="ck_daily_report_profiles_window",
        ),
        CheckConstraint(
            "temperature_min_c IS NULL OR temperature_max_c IS NULL "
            "OR temperature_min_c < temperature_max_c",
            name="ck_daily_report_profiles_temperature_limits",
        ),
        Index(
            "ix_daily_report_profiles_organization_enabled",
            "organization_id",
            "enabled",
            "equipment_id",
            "name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_daily_report_profiles_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    equipment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Europe/Kyiv",
        server_default="Europe/Kyiv",
    )
    report_hour: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default=text("7"),
    )
    report_minute: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
        server_default=text("50"),
    )
    weekdays: Mapped[list[int]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: [0, 1, 2, 3, 4],
        server_default=text("'[0,1,2,3,4]'"),
    )
    analysis_window_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=720,
        server_default=text("720"),
    )
    m_packet_channels: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
    )
    temperature_min_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_max_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    energy_source: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class RefrigerationDailyReportSnapshot(Base):
    __tablename__ = "refrigeration_daily_report_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "profile_id"],
            [
                "refrigeration_daily_report_profiles.organization_id",
                "refrigeration_daily_report_profiles.id",
            ],
            name="fk_daily_report_snapshots_profile",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_daily_report_snapshots_equipment",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "profile_id",
            "local_report_date",
            name="uq_daily_report_snapshots_profile_date",
        ),
        CheckConstraint(
            f"status IN ({_REPORT_STATUS_SQL})",
            name="ck_daily_report_snapshots_status",
        ),
        CheckConstraint(
            "window_end > window_start",
            name="ck_daily_report_snapshots_window",
        ),
        Index(
            "ix_daily_report_snapshots_organization_scheduled",
            "organization_id",
            "scheduled_for",
            "profile_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    local_report_date: Mapped[date] = mapped_column(Date(), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
