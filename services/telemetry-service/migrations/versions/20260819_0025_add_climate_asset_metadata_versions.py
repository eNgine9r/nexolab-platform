"""add optimistic metadata versions to climate catalog assets

Revision ID: 20260819_0025
Revises: 20260807_0024
Create Date: 2026-08-19 18:55:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260819_0025"
down_revision = "20260807_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("measurement_devices", "physical_sensors"):
        op.add_column(
            table_name,
            sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        )


def downgrade() -> None:
    for table_name in ("physical_sensors", "measurement_devices"):
        op.drop_column(table_name, "version")
