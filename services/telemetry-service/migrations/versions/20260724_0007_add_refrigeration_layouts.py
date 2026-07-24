"""add refrigeration layout drafts, publications and equipment images

Revision ID: 20260724_0007
Revises: 20260724_0006
Create Date: 2026-07-24 23:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260724_0007"
down_revision = "20260724_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment_images",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=False),
        sa.Column("height_px", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_etag", sa.String(length=128), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_equipment_images_size_positive"),
        sa.CheckConstraint("width_px > 0", name="ck_equipment_images_width_positive"),
        sa.CheckConstraint("height_px > 0", name="ck_equipment_images_height_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_equipment_images_equipment_created",
        "equipment_images",
        ["equipment_id", "created_at"],
    )

    op.create_table(
        "refrigeration_layout_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=True),
        sa.Column("placements", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
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
        sa.CheckConstraint(
            "version >= 1", name="ck_refrigeration_layout_draft_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["equipment_images.id"],
            name="fk_layout_draft_image_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "equipment_id", name="uq_refrigeration_layout_draft_equipment"
        ),
    )
    op.create_index(
        "ix_refrigeration_layout_drafts_updated",
        "refrigeration_layout_drafts",
        ["updated_at"],
    )

    op.create_table(
        "refrigeration_layout_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("equipment_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_draft_version", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.String(length=36), nullable=False),
        sa.Column("placements", sa.JSON(), nullable=False),
        sa.Column("published_by", sa.String(length=128), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_refrigeration_layout_revision_positive"
        ),
        sa.CheckConstraint(
            "source_draft_version >= 1",
            name="ck_refrigeration_layout_revision_source_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["image_id"],
            ["equipment_images.id"],
            name="fk_layout_revision_image_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "equipment_id",
            "revision",
            name="uq_refrigeration_layout_revision_equipment",
        ),
    )
    op.create_index(
        "ix_refrigeration_layout_revisions_equipment_published",
        "refrigeration_layout_revisions",
        ["equipment_id", "published_at"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION reject_refrigeration_layout_revision_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'refrigeration layout revisions are immutable';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_refrigeration_layout_revisions_immutable
            BEFORE UPDATE OR DELETE ON refrigeration_layout_revisions
            FOR EACH ROW EXECUTE FUNCTION reject_refrigeration_layout_revision_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_refrigeration_layout_revisions_immutable "
            "ON refrigeration_layout_revisions"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS reject_refrigeration_layout_revision_mutation()"
        )

    op.drop_index(
        "ix_refrigeration_layout_revisions_equipment_published",
        table_name="refrigeration_layout_revisions",
    )
    op.drop_table("refrigeration_layout_revisions")
    op.drop_index(
        "ix_refrigeration_layout_drafts_updated",
        table_name="refrigeration_layout_drafts",
    )
    op.drop_table("refrigeration_layout_drafts")
    op.drop_index(
        "ix_equipment_images_equipment_created",
        table_name="equipment_images",
    )
    op.drop_table("equipment_images")
