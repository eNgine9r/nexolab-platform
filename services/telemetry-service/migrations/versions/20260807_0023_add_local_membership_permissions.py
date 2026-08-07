"""add local membership permissions and laboratory technician role

Revision ID: 20260807_0023
Revises: 20260805_0022
Create Date: 2026-08-07 23:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260807_0023"
down_revision = "20260805_0022"
branch_labels = None
depends_on = None

_MIGRATION_ACTOR = "migration:20260807_0023"

_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "laboratory_manager": (
        "dashboard.read",
        "live_dashboards.manage",
        "telemetry.read",
        "alerts.read",
        "audit.read",
        "reports.read",
        "nodes.read",
        "reports.generate",
        "equipment.manage",
        "nodes.manage",
        "layout.draft.edit",
        "layout.publish",
        "layout.restore",
        "sessions.manage",
        "sessions.operate",
        "alerts.rules.manage",
        "alerts.acknowledge",
        "reports.approve",
    ),
    "engineer": (
        "dashboard.read",
        "live_dashboards.manage",
        "telemetry.read",
        "alerts.read",
        "reports.read",
        "nodes.read",
        "reports.generate",
        "equipment.manage",
        "layout.draft.edit",
        "layout.publish",
        "layout.restore",
        "sessions.manage",
        "sessions.operate",
        "alerts.acknowledge",
    ),
    "operator": (
        "dashboard.read",
        "live_dashboards.manage",
        "telemetry.read",
        "alerts.read",
        "reports.read",
        "nodes.read",
        "layout.draft.edit",
        "sessions.operate",
        "alerts.acknowledge",
    ),
    "viewer": (
        "dashboard.read",
        "telemetry.read",
        "alerts.read",
        "reports.read",
        "nodes.read",
    ),
    "auditor": (
        "dashboard.read",
        "telemetry.read",
        "alerts.read",
        "audit.read",
        "reports.read",
        "nodes.read",
    ),
}

_ROLE_CHECK = (
    "role IN ('administrator', 'laboratory_manager', 'engineer', "
    "'laboratory_technician', 'operator', 'viewer', 'auditor')"
)
_OLD_ROLE_CHECK = (
    "role IN ('administrator', 'laboratory_manager', 'engineer', "
    "'operator', 'viewer', 'auditor')"
)

_PERMISSION_CHECK = (
    "permission IN ("
    "'dashboard.read', 'live_dashboards.manage', 'telemetry.read', "
    "'alerts.read', 'audit.read', 'reports.read', 'nodes.read', "
    "'reports.generate', 'memberships.manage', 'equipment.manage', "
    "'nodes.manage', 'layout.draft.edit', 'layout.publish', "
    "'layout.restore', 'sessions.manage', 'sessions.operate', "
    "'alerts.rules.manage', 'alerts.acknowledge', 'reports.approve', "
    "'project_versions.manage'"
    ")"
)


def upgrade() -> None:
    with op.batch_alter_table("security_membership_roles") as batch:
        batch.drop_constraint(
            "ck_security_membership_role_known",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_security_membership_role_known",
            _ROLE_CHECK,
        )

    op.create_table(
        "security_membership_permissions",
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("permission", sa.String(length=128), nullable=False),
        sa.Column("assigned_by", sa.String(length=255), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            _PERMISSION_CHECK,
            name="ck_security_membership_permission_known",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["security_organization_memberships.id"],
            name="fk_security_membership_permission_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("membership_id", "permission"),
    )
    op.create_index(
        "ix_security_membership_permissions_permission",
        "security_membership_permissions",
        ["permission"],
    )

    # Keep the backfill renderable by `alembic upgrade head --sql`: no database
    # reads are performed while the migration script itself is being generated.
    grants = [
        (role, permission)
        for role, permissions in _ROLE_PERMISSIONS.items()
        for permission in permissions
    ]
    values_sql = ",\n        ".join(
        f"('{role}', '{permission}')" for role, permission in grants
    )
    op.execute(
        sa.text(
            "INSERT INTO security_membership_permissions "
            "(membership_id, permission, assigned_by)\n"
            "SELECT roles.membership_id, grants.permission, "
            f"'{_MIGRATION_ACTOR}'\n"
            "FROM security_membership_roles AS roles\n"
            f"JOIN (VALUES\n        {values_sql}\n"
            ") AS grants(role, permission) ON grants.role = roles.role\n"
            "ON CONFLICT (membership_id, permission) DO NOTHING"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    technician_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM security_membership_roles "
            "WHERE role = 'laboratory_technician'"
        )
    ).scalar_one()
    changed_grant_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM security_membership_permissions "
            "WHERE assigned_by IS NULL OR assigned_by <> :actor"
        ),
        {"actor": _MIGRATION_ACTOR},
    ).scalar_one()
    if technician_count:
        raise RuntimeError(
            "cannot downgrade while laboratory_technician memberships exist"
        )
    if changed_grant_count:
        raise RuntimeError(
            "cannot downgrade after administrator-managed permission changes"
        )

    op.drop_index(
        "ix_security_membership_permissions_permission",
        table_name="security_membership_permissions",
    )
    op.drop_table("security_membership_permissions")

    with op.batch_alter_table("security_membership_roles") as batch:
        batch.drop_constraint(
            "ck_security_membership_role_known",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_security_membership_role_known",
            _OLD_ROLE_CHECK,
        )
