"""add telemetry session attribution context

Revision ID: 20260724_0005
Revises: 20260724_0004
Create Date: 2026-07-24 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260724_0005"
down_revision = "20260724_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_session_contexts",
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("binding_id", sa.String(length=36), nullable=False),
        sa.Column("stage_id", sa.String(length=36), nullable=True),
        sa.Column("config_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("session_state", sa.String(length=32), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attributed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "session_state IN ('running', 'paused')",
            name="ck_telemetry_session_context_state",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["telemetry_samples.event_id"],
            name="fk_telemetry_context_event_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["test_sessions.id"],
            name="fk_telemetry_context_session_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["session_channel_bindings.id"],
            name="fk_telemetry_context_binding_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["session_stages.id"],
            name="fk_telemetry_context_stage_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_snapshot_id"],
            ["session_config_snapshots.id"],
            name="fk_telemetry_context_config_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_telemetry_context_session_captured",
        "telemetry_session_contexts",
        ["session_id", "captured_at", "event_id"],
    )
    op.create_index(
        "ix_telemetry_context_stage_captured",
        "telemetry_session_contexts",
        ["stage_id", "captured_at", "event_id"],
    )
    op.create_index(
        "ix_telemetry_context_binding_captured",
        "telemetry_session_contexts",
        ["binding_id", "captured_at", "event_id"],
    )
    op.create_index(
        "ix_telemetry_context_snapshot_captured",
        "telemetry_session_contexts",
        ["config_snapshot_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_telemetry_context_snapshot_captured",
        table_name="telemetry_session_contexts",
    )
    op.drop_index(
        "ix_telemetry_context_binding_captured",
        table_name="telemetry_session_contexts",
    )
    op.drop_index(
        "ix_telemetry_context_stage_captured",
        table_name="telemetry_session_contexts",
    )
    op.drop_index(
        "ix_telemetry_context_session_captured",
        table_name="telemetry_session_contexts",
    )
    op.drop_table("telemetry_session_contexts")
