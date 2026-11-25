"""Allow dashboards to reference observed standalone series."""

import sqlalchemy as sa
from alembic import op

revision = "20261116_0038"
down_revision = "20260908_0037"
branch_labels = None
depends_on = None

TABLE = "live_dashboard_items"
SOURCE_CHECK = "ck_live_dashboard_items_channel_source"
SERIES_UNIQUE = "uq_live_dashboard_items_observed_series"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("node_id", sa.String(128), nullable=True))
    op.add_column(TABLE, sa.Column("equipment_id", sa.String(128), nullable=True))
    op.alter_column(TABLE, "channel_ref_id", existing_type=sa.String(36), nullable=True)
    op.create_check_constraint(
        SOURCE_CHECK,
        TABLE,
        "(channel_ref_id IS NOT NULL AND node_id IS NULL AND equipment_id IS NULL) OR "
        "(channel_ref_id IS NULL AND node_id IS NOT NULL AND equipment_id IS NOT NULL)",
    )
    op.create_unique_constraint(
        SERIES_UNIQUE,
        TABLE,
        ["organization_id", "dashboard_id", "node_id", "equipment_id", "channel_id", "metric"],
    )


def downgrade() -> None:
    # This fails transactionally if any standalone selections still exist.
    op.alter_column(TABLE, "channel_ref_id", existing_type=sa.String(36), nullable=False)
    op.drop_constraint(SERIES_UNIQUE, TABLE, type_="unique")
    op.drop_constraint(SOURCE_CHECK, TABLE, type_="check")
    op.drop_column(TABLE, "equipment_id")
    op.drop_column(TABLE, "node_id")
