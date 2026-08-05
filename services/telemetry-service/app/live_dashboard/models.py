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


class LiveDashboard(Base):
    __tablename__ = "live_dashboards"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "id",
            name="uq_live_dashboards_organization_id",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_live_dashboards_status",
        ),
        CheckConstraint(
            "refresh_seconds IN (1, 2, 5, 10, 15, 30, 60)",
            name="ck_live_dashboards_refresh_seconds",
        ),
        CheckConstraint(
            "time_window IN ('5m', '15m', '30m', '1h', '6h', '12h', '24h', '7d')",
            name="ck_live_dashboards_time_window",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_live_dashboards_version_positive",
        ),
        Index(
            "ix_live_dashboards_organization_status_updated",
            "organization_id",
            "status",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "security_organizations.id",
            name="fk_live_dashboards_organization",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    owner_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    refresh_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        server_default=text("5"),
    )
    time_window: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="15m",
        server_default="15m",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default="active",
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_by: Mapped[str] = mapped_column(String(255), nullable=False)
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
    archived_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class LiveDashboardItem(Base):
    __tablename__ = "live_dashboard_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "dashboard_id"],
            ["live_dashboards.organization_id", "live_dashboards.id"],
            name="fk_live_dashboard_items_dashboard",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "channel_ref_id"],
            ["measurement_channels.organization_id", "measurement_channels.id"],
            name="fk_live_dashboard_items_channel",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "organization_id",
            "dashboard_id",
            "position",
            name="uq_live_dashboard_items_position",
        ),
        UniqueConstraint(
            "organization_id",
            "dashboard_id",
            "channel_ref_id",
            "metric",
            name="uq_live_dashboard_items_channel_metric",
        ),
        CheckConstraint(
            "position BETWEEN 1 AND 64",
            name="ck_live_dashboard_items_position",
        ),
        CheckConstraint(
            "visualization IN ('line', 'area', 'gauge', 'value')",
            name="ck_live_dashboard_items_visualization",
        ),
        Index(
            "ix_live_dashboard_items_dashboard_order",
            "organization_id",
            "dashboard_id",
            "position",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dashboard_id: Mapped[str] = mapped_column(String(36), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    channel_ref_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    native_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    visualization: Mapped[str] = mapped_column(String(16), nullable=False)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    display_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
