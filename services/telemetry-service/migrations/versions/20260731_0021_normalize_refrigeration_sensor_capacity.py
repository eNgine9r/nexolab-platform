"""normalize refrigeration sensor slot capacity

Revision ID: 20260731_0021
Revises: 20260730_0020
Create Date: 2026-07-31 10:25:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260731_0021"
down_revision = "20260730_0020"
branch_labels = None
depends_on = None

DEFAULT_SENSOR_SLOT_CAPACITY = 48


def upgrade() -> None:
    op.execute(
        """
        UPDATE refrigeration_equipment
        SET total_sensors = 48,
            updated_at = CURRENT_TIMESTAMP
        WHERE total_sensors = 0
          AND deleted_at IS NULL
          AND lifecycle_status IN ('active', 'maintenance')
        """
    )
    op.alter_column(
        "refrigeration_equipment",
        "total_sensors",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text(str(DEFAULT_SENSOR_SLOT_CAPACITY)),
    )


def downgrade() -> None:
    op.alter_column(
        "refrigeration_equipment",
        "total_sensors",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=sa.text("0"),
    )
