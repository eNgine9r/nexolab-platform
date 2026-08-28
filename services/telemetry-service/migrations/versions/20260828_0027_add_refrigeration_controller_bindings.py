"""add refrigeration controller bindings

Revision ID: 20260828_0027
Revises: 20260820_0026
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260828_0027"
down_revision = "20260820_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refrigeration_controller_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=64), nullable=False),
        sa.Column("controller_family", sa.String(length=32), nullable=False),
        sa.Column("controller_equipment_id", sa.String(length=128), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("bound_by", sa.String(length=128), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_by", sa.String(length=128), nullable=True),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "controller_family IN ('embraco')",
            name="ck_refrigeration_controller_binding_family",
        ),
        sa.CheckConstraint(
            "unit_id BETWEEN 1 AND 247",
            name="ck_refrigeration_controller_binding_unit",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_refrigeration_controller_binding_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "equipment_id"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_refrigeration_controller_binding_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_refrigeration_controller_binding_active_equipment",
        "refrigeration_controller_bindings",
        ["organization_id", "equipment_id"],
        unique=True,
        postgresql_where=sa.text("unbound_at IS NULL"),
    )
    op.create_index(
        "uq_refrigeration_controller_binding_active_identity",
        "refrigeration_controller_bindings",
        ["organization_id", "node_id", "controller_family", "unit_id"],
        unique=True,
        postgresql_where=sa.text("unbound_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_refrigeration_controller_binding_active_identity",
        table_name="refrigeration_controller_bindings",
    )
    op.drop_index(
        "uq_refrigeration_controller_binding_active_equipment",
        table_name="refrigeration_controller_bindings",
    )
    op.drop_table("refrigeration_controller_bindings")
