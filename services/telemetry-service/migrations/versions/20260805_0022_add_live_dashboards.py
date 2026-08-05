"""add persisted Live Dashboard domain

Revision ID: 20260805_0022
Revises: 20260801_0021
Create Date: 2026-08-05 14:55:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260805_0022"
down_revision = "20260801_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_dashboards",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("owner_subject", sa.String(length=255), nullable=False),
        sa.Column(
            "refresh_seconds",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "time_window",
            sa.String(length=8),
            server_default=sa.text("'15m'"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("archived_by", sa.String(length=255), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_live_dashboards_status",
        ),
        sa.CheckConstraint(
            "refresh_seconds IN (1, 2, 5, 10, 15, 30, 60)",
            name="ck_live_dashboards_refresh_seconds",
        ),
        sa.CheckConstraint(
            "time_window IN ('5m', '15m', '30m', '1h', '6h', '12h', '24h', '7d')",
            name="ck_live_dashboards_time_window",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_live_dashboards_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_live_dashboards_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name="uq_live_dashboards_organization_id",
        ),
    )
    op.create_index(
        "ix_live_dashboards_organization_status_updated",
        "live_dashboards",
        ["organization_id", "status", "updated_at", "id"],
    )

    op.create_table(
        "live_dashboard_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("dashboard_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("channel_ref_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("native_unit", sa.String(length=32), nullable=False),
        sa.Column("visualization", sa.String(length=16), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=True),
        sa.Column("display_unit", sa.String(length=32), nullable=True),
        sa.CheckConstraint(
            "position BETWEEN 1 AND 64",
            name="ck_live_dashboard_items_position",
        ),
        sa.CheckConstraint(
            "visualization IN ('line', 'area', 'gauge', 'value')",
            name="ck_live_dashboard_items_visualization",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "dashboard_id"],
            ["live_dashboards.organization_id", "live_dashboards.id"],
            name="fk_live_dashboard_items_dashboard",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "channel_ref_id"],
            ["measurement_channels.organization_id", "measurement_channels.id"],
            name="fk_live_dashboard_items_channel",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "dashboard_id",
            "position",
            name="uq_live_dashboard_items_position",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "dashboard_id",
            "channel_ref_id",
            "metric",
            name="uq_live_dashboard_items_channel_metric",
        ),
    )
    op.create_index(
        "ix_live_dashboard_items_dashboard_order",
        "live_dashboard_items",
        ["organization_id", "dashboard_id", "position", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_dashboard_items_dashboard_order",
        table_name="live_dashboard_items",
    )
    op.drop_table("live_dashboard_items")
    op.drop_index(
        "ix_live_dashboards_organization_status_updated",
        table_name="live_dashboards",
    )
    op.drop_table("live_dashboards")
