"""Add opt-in central committed receipt intents (no publisher or rollout).

Revision ID: 20261030_0038
Revises: 20260908_0037
"""
from alembic import op
import sqlalchemy as sa

revision = "20261030_0038"
down_revision = "20260908_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_committed_receipts",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("receipt_id", sa.String(36), nullable=False, unique=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(128), nullable=False),
        sa.Column("node_sequence", sa.BigInteger(), nullable=False),
        sa.Column("topic", sa.String(256), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_telemetry_committed_receipts_pending",
        "telemetry_committed_receipts",
        ["published_at", "committed_at"],
    )
    op.create_index(
        "uq_telemetry_committed_receipts_node_sequence",
        "telemetry_committed_receipts",
        ["organization_id", "node_id", "node_sequence"],
        unique=True,
    )


def downgrade() -> None:
    # A downgrade must not silently discard unacknowledged application receipts.
    connection = op.get_bind()
    count = connection.scalar(sa.text(
        "SELECT count(*) FROM telemetry_committed_receipts"
    ))
    if count:
        raise RuntimeError("receipt_outbox_not_empty_downgrade_refused")
    op.drop_index("uq_telemetry_committed_receipts_node_sequence")
    op.drop_index("ix_telemetry_committed_receipts_pending")
    op.drop_table("telemetry_committed_receipts")
