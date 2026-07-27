"""add encrypted node broker command outbox

Revision ID: 20260727_0016
Revises: 20260727_0015
Create Date: 2026-07-27 13:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260727_0016"
down_revision = "20260727_0015"
branch_labels = None
depends_on = None


COMMAND_TYPES = "'upsert_credential', 'disable_client', 'enable_client'"
COMMAND_STATES = "'pending', 'retrying', 'applied', 'failed'"


def upgrade() -> None:
    op.create_table(
        "central_node_broker_commands",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("node_record_id", sa.String(length=36), nullable=False),
        sa.Column("credential_id", sa.String(length=36), nullable=True),
        sa.Column("command_type", sa.String(length=32), nullable=False),
        sa.Column("command_key", sa.String(length=160), nullable=False),
        sa.Column("command_sha256", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=True),
        sa.Column(
            "desired_enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_nonce", sa.String(length=64), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=32), nullable=True),
        sa.Column(
            "state", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column(
            "attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "max_attempts", sa.Integer(), server_default=sa.text("8"), nullable=False
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_summary", sa.String(length=1024), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"command_type IN ({COMMAND_TYPES})",
            name="ck_central_node_broker_commands_type",
        ),
        sa.CheckConstraint(
            f"state IN ({COMMAND_STATES})",
            name="ck_central_node_broker_commands_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts >= 1",
            name="ck_central_node_broker_commands_attempts",
        ),
        sa.CheckConstraint(
            "(command_type = 'upsert_credential' AND credential_id IS NOT NULL "
            "AND secret_ciphertext IS NOT NULL AND secret_nonce IS NOT NULL "
            "AND encryption_key_id IS NOT NULL AND credential_generation IS NOT NULL) "
            "OR (command_type <> 'upsert_credential' AND credential_id IS NULL "
            "AND secret_ciphertext IS NULL AND secret_nonce IS NULL "
            "AND encryption_key_id IS NULL AND credential_generation IS NULL)",
            name="ck_central_node_broker_commands_secret_shape",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_central_node_broker_commands_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["node_record_id"],
            ["central_nodes.id"],
            name="fk_central_node_broker_commands_node",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["central_node_credentials.id"],
            name="fk_central_node_broker_commands_credential",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "command_key",
            name="uq_central_node_broker_commands_organization_key",
        ),
    )
    op.create_index(
        "ix_central_node_broker_commands_dispatch",
        "central_node_broker_commands",
        ["state", "available_at", "created_at"],
    )
    op.create_index(
        "ix_central_node_broker_commands_node_history",
        "central_node_broker_commands",
        ["organization_id", "node_record_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_central_node_broker_commands_node_history",
        table_name="central_node_broker_commands",
    )
    op.drop_index(
        "ix_central_node_broker_commands_dispatch",
        table_name="central_node_broker_commands",
    )
    op.drop_table("central_node_broker_commands")
