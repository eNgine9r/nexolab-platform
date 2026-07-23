"""add telemetry query indexes

Revision ID: 20260723_0002
Revises: 20260723_0001
Create Date: 2026-07-23 13:15:00
"""
from __future__ import annotations

from alembic import op

revision = "20260723_0002"
down_revision = "20260723_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_telemetry_latest_lookup",
        "telemetry_samples",
        [
            "node_id",
            "equipment_id",
            "channel_id",
            "metric",
            "captured_at",
            "event_id",
        ],
    )
    op.create_index(
        "ix_telemetry_history_lookup",
        "telemetry_samples",
        ["node_id", "channel_id", "captured_at", "event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telemetry_history_lookup", table_name="telemetry_samples")
    op.drop_index("ix_telemetry_latest_lookup", table_name="telemetry_samples")
