"""add local operator accounts and refresh sessions

Revision ID: 20260801_0021
Revises: 20260730_0020
Create Date: 2026-08-01 20:35:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_0021"
down_revision = "20260730_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "security_local_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["security_identities.id"],
            name="fk_security_local_account_identity",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identity_id", name="uq_security_local_accounts_identity"),
        sa.UniqueConstraint("username", name="uq_security_local_accounts_username"),
    )
    op.create_index(
        "ix_security_local_accounts_active_username",
        "security_local_accounts",
        ["is_active", "username"],
    )

    op.create_table(
        "security_local_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("account_id", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["security_local_accounts.id"],
            name="fk_security_local_session_account",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "refresh_token_hash",
            name="uq_security_local_sessions_refresh_hash",
        ),
    )
    op.create_index(
        "ix_security_local_sessions_account_active",
        "security_local_sessions",
        ["account_id", "revoked_at", "expires_at"],
    )
    op.create_index(
        "ix_security_local_sessions_expires",
        "security_local_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_local_sessions_expires",
        table_name="security_local_sessions",
    )
    op.drop_index(
        "ix_security_local_sessions_account_active",
        table_name="security_local_sessions",
    )
    op.drop_table("security_local_sessions")
    op.drop_index(
        "ix_security_local_accounts_active_username",
        table_name="security_local_accounts",
    )
    op.drop_table("security_local_accounts")
