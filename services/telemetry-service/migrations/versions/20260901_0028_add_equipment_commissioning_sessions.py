"""add equipment commissioning sessions

Revision ID: 20260901_0028
Revises: 20260828_0027
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260901_0028"
down_revision = "20260828_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_commissioning_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("create_idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("create_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("lifecycle", sa.String(length=32), nullable=False),
        sa.Column("device_class", sa.String(length=64), nullable=False),
        sa.Column("manufacturer", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=True),
        sa.Column("profile_version", sa.String(length=128), nullable=True),
        sa.Column("transport_kind", sa.String(length=32), nullable=True),
        sa.Column("node_id", sa.String(length=64), nullable=True),
        sa.Column("bus_id", sa.String(length=64), nullable=True),
        sa.Column("stable_transport_identifier", sa.String(length=255), nullable=True),
        sa.Column("unit_id", sa.Integer(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("target_equipment_key", sa.String(length=255), nullable=True),
        sa.Column("blocked_reason", sa.String(length=1024), nullable=True),
        sa.Column("unsupported_reason", sa.String(length=1024), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "lifecycle IN ('draft', 'ready_for_preflight', 'blocked', 'unsupported', 'cancelled')",
            name="ck_equipment_commissioning_session_lifecycle",
        ),
        sa.CheckConstraint("version >= 1", name="ck_equipment_commissioning_session_version"),
        sa.CheckConstraint(
            "unit_id IS NULL OR (unit_id BETWEEN 1 AND 247)",
            name="ck_equipment_commissioning_session_unit_id",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_equipment_commissioning_session_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "target_equipment_key"],
            ["refrigeration_equipment.organization_id", "refrigeration_equipment.id"],
            name="fk_equipment_commissioning_session_target_equipment",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "create_idempotency_key",
            name="uq_equipment_commissioning_session_create_key",
        ),
    )
    op.create_index(
        "ix_equipment_commissioning_session_organization_updated",
        "equipment_commissioning_sessions",
        ["organization_id", "updated_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_equipment_commissioning_session_organization_updated",
        table_name="equipment_commissioning_sessions",
    )
    op.drop_table("equipment_commissioning_sessions")
