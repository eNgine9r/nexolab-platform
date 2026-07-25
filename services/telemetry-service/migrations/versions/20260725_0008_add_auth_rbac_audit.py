"""add authentication, organization RBAC and platform audit

Revision ID: 20260725_0008
Revises: 20260724_0007
Create Date: 2026-07-25 13:15:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260725_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
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
        "auth_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=256), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("subject"),
    )
    op.create_index("ix_auth_identities_email", "auth_identities", ["email"])

    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("identity_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["auth_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id",
            "identity_id",
            name="uq_organization_membership_identity",
        ),
    )
    op.create_index(
        "ix_organization_memberships_org_role",
        "organization_memberships",
        ["organization_id", "role"],
    )

    op.create_table(
        "resource_organization_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=False),
        sa.Column("created_by_identity_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_identity_id"],
            ["auth_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "resource_type",
            "resource_id",
            name="uq_resource_organization_binding_resource",
        ),
    )
    op.create_index(
        "ix_resource_organization_bindings_org_resource",
        "resource_organization_bindings",
        ["organization_id", "resource_type", "resource_id"],
    )

    op.create_table(
        "platform_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=128), nullable=True),
        sa.Column("actor_identity_id", sa.String(length=36), nullable=True),
        sa.Column("actor_subject", sa.String(length=256), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=256), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("metadata_payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_identity_id"],
            ["auth_identities.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_platform_audit_org_occurred",
        "platform_audit_events",
        ["organization_id", "occurred_at"],
    )
    op.create_index(
        "ix_platform_audit_resource_occurred",
        "platform_audit_events",
        ["resource_type", "resource_id", "occurred_at"],
    )
    op.create_index(
        "ix_platform_audit_actor_occurred",
        "platform_audit_events",
        ["actor_subject", "occurred_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_platform_audit_event_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'platform audit events are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_platform_audit_events_immutable
            BEFORE UPDATE OR DELETE ON platform_audit_events
            FOR EACH ROW EXECUTE FUNCTION reject_platform_audit_event_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_platform_audit_events_immutable "
            "ON platform_audit_events"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_platform_audit_event_mutation()")

    op.drop_index("ix_platform_audit_actor_occurred", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_resource_occurred", table_name="platform_audit_events")
    op.drop_index("ix_platform_audit_org_occurred", table_name="platform_audit_events")
    op.drop_table("platform_audit_events")
    op.drop_index(
        "ix_resource_organization_bindings_org_resource",
        table_name="resource_organization_bindings",
    )
    op.drop_table("resource_organization_bindings")
    op.drop_index(
        "ix_organization_memberships_org_role",
        table_name="organization_memberships",
    )
    op.drop_table("organization_memberships")
    op.drop_index("ix_auth_identities_email", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("organizations")
