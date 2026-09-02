"""add controlled commissioning activation

Revision ID: 20260902_0030
Revises: 20260902_0029
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260902_0030"
down_revision = "20260902_0029"
branch_labels = None
depends_on = None

_SESSION_LIFECYCLES = (
    "lifecycle IN ('draft', 'ready_for_preflight', 'verified', "
    "'pending_activation', 'active', 'activation_failed', 'rolled_back', "
    "'blocked', 'unsupported', 'cancelled')"
)


def upgrade() -> None:
    with op.batch_alter_table("equipment_commissioning_sessions") as batch:
        batch.drop_constraint(
            "ck_equipment_commissioning_session_lifecycle", type_="check"
        )
        batch.create_check_constraint(
            "ck_equipment_commissioning_session_lifecycle", _SESSION_LIFECYCLES
        )
    op.create_table(
        "equipment_commissioning_activation_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("preflight_attempt_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending_activation', 'active', 'activation_failed', "
            "'rolled_back', 'recovery_required')",
            name="ck_equipment_commissioning_activation_state",
        ),
        sa.CheckConstraint(
            "session_version >= 1",
            name="ck_equipment_commissioning_activation_session_version",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["security_organizations.id"],
            name="fk_equipment_commissioning_activation_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["equipment_commissioning_sessions.id"],
            name="fk_equipment_commissioning_activation_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preflight_attempt_id"],
            ["equipment_commissioning_preflight_attempts.id"],
            name="fk_equipment_commissioning_activation_preflight",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "session_id", "idempotency_key",
            name="uq_equipment_commissioning_activation_attempt_key",
        ),
    )
    op.create_index(
        "ix_equipment_commissioning_activation_session_started",
        "equipment_commissioning_activation_attempts",
        ["organization_id", "session_id", "started_at", "id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_equipment_commissioning_activation_session_started",
        table_name="equipment_commissioning_activation_attempts",
    )
    op.drop_table("equipment_commissioning_activation_attempts")
    with op.batch_alter_table("equipment_commissioning_sessions") as batch:
        batch.drop_constraint(
            "ck_equipment_commissioning_session_lifecycle", type_="check"
        )
        batch.create_check_constraint(
            "ck_equipment_commissioning_session_lifecycle",
            "lifecycle IN ('draft', 'ready_for_preflight', 'blocked', "
            "'unsupported', 'cancelled')",
        )
