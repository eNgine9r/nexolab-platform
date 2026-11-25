"""Store instrument names independently of refrigeration passports.

Revision ID: 20261104_0038
Revises: 20260908_0037
"""
from alembic import op
import sqlalchemy as sa

revision = "20261104_0038"
down_revision = "20260908_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("equipment_commissioning_sessions", sa.Column("display_name", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("equipment_commissioning_sessions", "display_name")
