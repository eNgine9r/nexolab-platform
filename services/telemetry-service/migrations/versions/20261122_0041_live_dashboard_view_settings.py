"""Saved analysis view settings for Saved Live Dashboards (#1666).

Adds one nullable JSON column. The change is additive and backward compatible: existing rows read
as "no saved view" and older clients that never send the field keep working. The downgrade refuses
to drop operator-authored views silently.

Revision ID: 20261122_0041
Revises: 20261118_0040
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_0041"
down_revision = "20261118_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("live_dashboards", sa.Column("view_settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    saved = connection.execute(
        sa.text("SELECT COUNT(*) FROM live_dashboards WHERE view_settings IS NOT NULL")
    ).scalar()
    if saved:
        raise RuntimeError(
            "Clear saved dashboard analysis views with an approved migration before downgrading"
        )
    op.drop_column("live_dashboards", "view_settings")
