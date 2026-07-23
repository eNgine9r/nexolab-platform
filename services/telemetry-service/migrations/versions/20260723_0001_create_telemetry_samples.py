"""create telemetry samples

Revision ID: 20260723_0001
Revises:
Create Date: 2026-07-23 12:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260723_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("node_id", sa.String(length=128), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric", sa.String(length=128), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("alarm", sa.String(length=32), nullable=True),
        sa.Column("raw_value", sa.BigInteger(), nullable=True),
        sa.Column("raw_status", sa.BigInteger(), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_index(
        "ix_telemetry_channel_captured",
        "telemetry_samples",
        ["node_id", "equipment_id", "channel_id", "captured_at"],
    )
    op.create_index(
        "ix_telemetry_metric_captured",
        "telemetry_samples",
        ["metric", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_metric_captured", table_name="telemetry_samples")
    op.drop_index("ix_telemetry_channel_captured", table_name="telemetry_samples")
    op.drop_table("telemetry_samples")
