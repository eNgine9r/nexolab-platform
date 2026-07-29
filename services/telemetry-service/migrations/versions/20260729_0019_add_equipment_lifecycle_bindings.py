"""add refrigeration equipment lifecycle and sensor bindings

Revision ID: 20260729_0019
Revises: 20260729_0018
Create Date: 2026-07-29 12:25:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260729_0019"
down_revision = "20260729_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "refrigeration_equipment",
        sa.Column("laboratory", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "refrigeration_equipment",
        sa.Column("zone", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "refrigeration_equipment",
        sa.Column("node_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "refrigeration_equipment",
        sa.Column(
            "lifecycle_status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )
    op.create_check_constraint(
        "ck_refrigeration_equipment_lifecycle_status",
        "refrigeration_equipment",
        "lifecycle_status IN ('active', 'maintenance', 'retired')",
    )
    op.drop_index("ix_refrigeration_equipment_active", table_name="refrigeration_equipment")
    op.create_index(
        "ix_refrigeration_equipment_active",
        "refrigeration_equipment",
        ["organization_id", "deleted_at", "lifecycle_status", "status", "name"],
        unique=False,
    )
    op.create_index(
        "ix_refrigeration_equipment_node",
        "refrigeration_equipment",
        ["organization_id", "node_id", "deleted_at"],
        unique=False,
    )

    op.add_column(
        "equipment_images",
        sa.Column("retired_by", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "equipment_images",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_index("ix_equipment_images_equipment_created", table_name="equipment_images")
    op.create_index(
        "ix_equipment_images_equipment_created",
        "equipment_images",
        ["organization_id", "equipment_id", "retired_at", "created_at"],
        unique=False,
    )

    op.create_table(
        "refrigeration_sensor_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("slot_key", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("shelf", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("bound_by", sa.String(length=128), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_by", sa.String(length=128), nullable=True),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("side IN ('front', 'rear')", name="ck_refrigeration_sensor_binding_side"),
        sa.CheckConstraint("shelf BETWEEN 1 AND 4", name="ck_refrigeration_sensor_binding_shelf"),
        sa.CheckConstraint("position BETWEEN 1 AND 6", name="ck_refrigeration_sensor_binding_position"),
        sa.CheckConstraint("version >= 1", name="ck_refrigeration_sensor_binding_version_positive"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_refrigeration_sensor_bindings_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_refrigeration_sensor_binding_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_refrigeration_sensor_bindings_equipment_history",
        "refrigeration_sensor_bindings",
        ["organization_id", "equipment_id", "bound_at"],
        unique=False,
    )
    op.create_index(
        "uq_refrigeration_sensor_bindings_active_channel",
        "refrigeration_sensor_bindings",
        ["organization_id", "node_id", "channel_id"],
        unique=True,
        postgresql_where=sa.text("unbound_at IS NULL"),
        sqlite_where=sa.text("unbound_at IS NULL"),
    )
    op.create_index(
        "uq_refrigeration_sensor_bindings_active_slot",
        "refrigeration_sensor_bindings",
        ["organization_id", "equipment_id", "slot_key"],
        unique=True,
        postgresql_where=sa.text("unbound_at IS NULL"),
        sqlite_where=sa.text("unbound_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_refrigeration_sensor_bindings_active_slot",
        table_name="refrigeration_sensor_bindings",
    )
    op.drop_index(
        "uq_refrigeration_sensor_bindings_active_channel",
        table_name="refrigeration_sensor_bindings",
    )
    op.drop_index(
        "ix_refrigeration_sensor_bindings_equipment_history",
        table_name="refrigeration_sensor_bindings",
    )
    op.drop_table("refrigeration_sensor_bindings")

    op.drop_index("ix_equipment_images_equipment_created", table_name="equipment_images")
    op.create_index(
        "ix_equipment_images_equipment_created",
        "equipment_images",
        ["organization_id", "equipment_id", "created_at"],
        unique=False,
    )
    op.drop_column("equipment_images", "retired_at")
    op.drop_column("equipment_images", "retired_by")

    op.drop_index("ix_refrigeration_equipment_node", table_name="refrigeration_equipment")
    op.drop_index("ix_refrigeration_equipment_active", table_name="refrigeration_equipment")
    op.create_index(
        "ix_refrigeration_equipment_active",
        "refrigeration_equipment",
        ["organization_id", "deleted_at", "status", "name"],
        unique=False,
    )
    op.drop_constraint(
        "ck_refrigeration_equipment_lifecycle_status",
        "refrigeration_equipment",
        type_="check",
    )
    op.drop_column("refrigeration_equipment", "lifecycle_status")
    op.drop_column("refrigeration_equipment", "node_id")
    op.drop_column("refrigeration_equipment", "zone")
    op.drop_column("refrigeration_equipment", "laboratory")
