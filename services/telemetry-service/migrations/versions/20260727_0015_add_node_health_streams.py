"""add node health and retained status streams

Revision ID: 20260727_0015
Revises: 20260726_0014
Create Date: 2026-07-27 05:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260727_0015"
down_revision = "20260726_0014"
branch_labels = None
depends_on = None


HEALTH_STATES = "'healthy', 'degraded'"
AVAILABILITY_STATES = "'online', 'offline'"


def upgrade() -> None:
    op.create_table(
        "central_node_health_samples",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("node_sequence", sa.BigInteger(), nullable=False),
        sa.Column("health", sa.String(length=16), nullable=False),
        sa.Column("uptime_seconds", sa.BigInteger(), nullable=False),
        sa.Column("queue_depth", sa.BigInteger(), nullable=False),
        sa.Column("samples_total", sa.BigInteger(), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=False),
        sa.Column("device_mode", sa.String(length=64), nullable=False),
        sa.Column("last_sample_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"health IN ({HEALTH_STATES})",
            name="ck_central_node_health_samples_health",
        ),
        sa.CheckConstraint(
            "node_sequence >= 1",
            name="ck_central_node_health_samples_sequence",
        ),
        sa.CheckConstraint(
            "uptime_seconds >= 0 AND queue_depth >= 0 AND samples_total >= 0",
            name="ck_central_node_health_samples_counters",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_health_samples_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_health_samples_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "event_id",
            name="uq_central_node_health_samples_organization_event",
        ),
        sa.UniqueConstraint(
            "node_record_id",
            "node_sequence",
            name="uq_central_node_health_samples_node_sequence",
        ),
    )
    op.create_index(
        "ix_central_node_health_samples_history",
        "central_node_health_samples",
        ["organization_id", "node_record_id", "captured_at"],
    )

    op.create_table(
        "central_node_status_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("node_sequence", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column("software_version", sa.String(length=64), nullable=True),
        sa.Column("graceful", sa.Boolean(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN ({AVAILABILITY_STATES})",
            name="ck_central_node_status_events_status",
        ),
        sa.CheckConstraint(
            "node_sequence >= 1",
            name="ck_central_node_status_events_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_status_events_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_status_events_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "event_id",
            name="uq_central_node_status_events_organization_event",
        ),
        sa.UniqueConstraint(
            "node_record_id",
            "node_sequence",
            name="uq_central_node_status_events_node_sequence",
        ),
    )
    op.create_index(
        "ix_central_node_status_events_history",
        "central_node_status_events",
        ["organization_id", "node_record_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_central_node_status_events_history",
        table_name="central_node_status_events",
    )
    op.drop_table("central_node_status_events")
    op.drop_index(
        "ix_central_node_health_samples_history",
        table_name="central_node_health_samples",
    )
    op.drop_table("central_node_health_samples")
