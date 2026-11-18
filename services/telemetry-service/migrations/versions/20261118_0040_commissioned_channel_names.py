"""Shared display names for commissioned temperature inputs.

Revision ID: 20261118_0040
Revises: 20261116_0039
"""
from alembic import op
import sqlalchemy as sa

revision = "20261118_0040"
down_revision = "20261116_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commissioned_channel_names",
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("channel_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("organization_id", "node_id", "channel_id", name="pk_commissioned_channel_names"),
        sa.ForeignKeyConstraint(["organization_id"], ["security_organizations.id"], name="fk_commissioned_channel_names_organization", ondelete="RESTRICT"),
    )


def downgrade() -> None:
    # Guard operator-authored labels; no destructive downgrade in a live installation.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT COUNT(*) FROM commissioned_channel_names")).scalar():
        raise RuntimeError("Clear commissioned channel display names with an approved migration first")
    op.drop_table("commissioned_channel_names")
