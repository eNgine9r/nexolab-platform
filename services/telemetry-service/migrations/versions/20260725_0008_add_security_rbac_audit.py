"""add organization RBAC and immutable security audit

Revision ID: 20260725_0008
Revises: 20260724_0007
Create Date: 2026-07-25 18:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260725_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None


ROLE_CHECK = (
    "role IN ('administrator', 'laboratory_manager', 'engineer', "
    "'operator', 'viewer', 'auditor')"
)


def upgrade() -> None:
    op.create_table(
        "security_organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )

    op.create_table(
        "security_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_authenticated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "subject",
            name="uq_security_identity_provider_subject",
        ),
    )
    op.create_index(
        "ix_security_identities_email",
        "security_identities",
        ["email"],
    )

    op.create_table(
        "security_organization_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["security_identities.id"],
            name="fk_security_membership_identity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_security_membership_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "identity_id",
            name="uq_security_membership_organization_identity",
        ),
    )
    op.create_index(
        "ix_security_memberships_identity",
        "security_organization_memberships",
        ["identity_id"],
    )

    op.create_table(
        "security_membership_roles",
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("assigned_by", sa.String(length=255), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(ROLE_CHECK, name="ck_security_membership_role_known"),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["security_organization_memberships.id"],
            name="fk_security_membership_role_membership",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("membership_id", "role"),
    )
    op.create_index(
        "ix_security_membership_roles_role",
        "security_membership_roles",
        ["role"],
    )

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("actor_identity_id", sa.String(length=36), nullable=True),
        sa.Column("actor_subject", sa.String(length=255), nullable=False),
        sa.Column("actor_roles", sa.JSON(), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=1024), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("source_ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"],
            ["security_identities.id"],
            name="fk_security_audit_identity",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["security_organizations.id"],
            name="fk_security_audit_organization",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_security_audit_organization_occurred",
        "security_audit_events",
        ["organization_id", "occurred_at"],
    )
    op.create_index(
        "ix_security_audit_entity",
        "security_audit_events",
        ["organization_id", "entity_type", "entity_id", "occurred_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_security_audit_event_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'security audit events are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_security_audit_events_immutable
            BEFORE UPDATE OR DELETE ON security_audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_security_audit_event_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_security_audit_events_immutable "
            "ON security_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_security_audit_event_mutation()")

    op.drop_index("ix_security_audit_entity", table_name="security_audit_events")
    op.drop_index(
        "ix_security_audit_organization_occurred",
        table_name="security_audit_events",
    )
    op.drop_table("security_audit_events")
    op.drop_index(
        "ix_security_membership_roles_role",
        table_name="security_membership_roles",
    )
    op.drop_table("security_membership_roles")
    op.drop_index(
        "ix_security_memberships_identity",
        table_name="security_organization_memberships",
    )
    op.drop_table("security_organization_memberships")
    op.drop_index("ix_security_identities_email", table_name="security_identities")
    op.drop_table("security_identities")
    op.drop_table("security_organizations")
