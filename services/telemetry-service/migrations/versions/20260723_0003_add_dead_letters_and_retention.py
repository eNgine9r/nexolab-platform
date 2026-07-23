"""add dead letters and raw payload retention

Revision ID: 20260723_0003
Revises: 20260723_0002
Create Date: 2026-07-23 14:45:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260723_0003"
down_revision = "20260723_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telemetry_samples",
        sa.Column(
            "raw_payload_retained",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )

    op.create_table(
        "telemetry_dead_letters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.String(length=256), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_detail", sa.String(length=2048), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("payload_size", sa.Integer(), nullable=False),
        sa.Column("payload_truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dead_letter_reason_received",
        "telemetry_dead_letters",
        ["reason_code", "received_at"],
    )
    op.create_index(
        "ix_dead_letter_received",
        "telemetry_dead_letters",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_dead_letter_received",
        table_name="telemetry_dead_letters",
    )
    op.drop_index(
        "ix_dead_letter_reason_received",
        table_name="telemetry_dead_letters",
    )
    op.drop_table("telemetry_dead_letters")
    op.drop_column("telemetry_samples", "raw_payload_retained")
