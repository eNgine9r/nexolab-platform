"""Add explicit navigation grants without altering existing resource access.

Revision ID: 20261106_0038
Revises: 20260908_0037
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261106_0038"
down_revision = "20260908_0037"
branch_labels = None
depends_on = None

_OLD_PERMISSIONS = (
    "dashboard.read", "live_dashboards.manage", "telemetry.read", "alerts.read",
    "audit.read", "reports.read", "nodes.read", "reports.generate", "reports.approve",
    "memberships.manage", "equipment.manage", "nodes.manage", "layout.draft.edit",
    "layout.publish", "layout.restore", "sessions.manage", "sessions.operate",
    "alerts.rules.manage", "alerts.acknowledge", "project_versions.manage",
)
_NAVIGATION_PERMISSIONS = (
    "navigation.overview", "navigation.nodes", "navigation.sessions", "navigation.live",
    "navigation.equipment_layouts", "navigation.lockers", "navigation.refrigeration",
    "navigation.alerts", "navigation.cameras", "navigation.energy", "navigation.reports",
    "navigation.equipment",
)
_BACKFILL = (
    ("dashboard.read", "navigation.overview"),
    ("dashboard.read", "navigation.sessions"),
    ("dashboard.read", "navigation.equipment_layouts"),
    ("dashboard.read", "navigation.refrigeration"),
    ("dashboard.read", "navigation.equipment"),
    ("nodes.read", "navigation.nodes"),
    ("telemetry.read", "navigation.live"),
    ("telemetry.read", "navigation.energy"),
    ("alerts.read", "navigation.alerts"),
    ("reports.read", "navigation.reports"),
)
_ACTOR = "migration:20261106_0038"


def upgrade() -> None:
    # PostgreSQL migrations hold this lock only within the migration transaction;
    # concurrent grant changes must not race the compatibility backfill.
    if op.get_context().dialect.name == "postgresql":
        op.execute("LOCK TABLE security_membership_permissions IN SHARE ROW EXCLUSIVE MODE")
    values = ", ".join(f"'{value}'" for value in (*_OLD_PERMISSIONS, *_NAVIGATION_PERMISSIONS))
    with op.batch_alter_table("security_membership_permissions") as batch:
        batch.drop_constraint("ck_security_membership_permission_known", type_="check")
        batch.create_check_constraint("ck_security_membership_permission_known", f"permission IN ({values})")

    # Preserve only existing visible destinations; cameras and planned lockers
    # were administrator-only before this migration and are not backfilled.
    for source, target in _BACKFILL:
        op.execute(sa.text(
            "INSERT INTO security_membership_permissions "
            "(membership_id, permission, assigned_by, assigned_at) "
            f"SELECT source.membership_id, '{target}', '{_ACTOR}', CURRENT_TIMESTAMP "
            "FROM security_membership_permissions AS source "
            f"WHERE source.permission = '{source}' AND NOT EXISTS ("
            "SELECT 1 FROM security_membership_permissions AS existing "
            "WHERE existing.membership_id = source.membership_id "
            f"AND existing.permission = '{target}')"
        ))


def downgrade() -> None:
    # An older frontend cannot enforce individually assigned navigation grants.
    # Silently deleting them or falling back would lose intent or broaden access.
    raise RuntimeError("navigation grants require a separately verified recovery plan before downgrade")
