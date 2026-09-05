"""add equipment commissioning preflight attempts

Revision ID: 20260902_0029
Revises: 20260901_0028
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260902_0029"
down_revision = "20260901_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_commissioning_preflight_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("evidence_level", sa.String(length=32), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('running', 'completed')",
            name="ck_equipment_commissioning_preflight_state",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('passed', 'failed')",
            name="ck_equipment_commissioning_preflight_result",
        ),
        sa.CheckConstraint(
            "evidence_level IS NULL OR evidence_level IN ('hardware_verified', 'partially_verified', 'unsupported', 'unverified')",
            name="ck_equipment_commissioning_preflight_evidence_level",
        ),
        sa.CheckConstraint(
            "session_version >= 1",
            name="ck_equipment_commissioning_preflight_session_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_equipment_commissioning_preflight_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["equipment_commissioning_sessions.id"],
            name="fk_equipment_commissioning_preflight_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "session_id",
            "idempotency_key",
            name="uq_equipment_commissioning_preflight_attempt_key",
        ),
    )
    op.create_index(
        "ix_equipment_commissioning_preflight_session_started",
        "equipment_commissioning_preflight_attempts",
        ["organization_id", "session_id", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_equipment_commissioning_preflight_session_started",
        table_name="equipment_commissioning_preflight_attempts",
    )
    op.drop_table("equipment_commissioning_preflight_attempts")
