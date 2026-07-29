from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect

from app.db import Base
from app.model_registry import register_models


REFRIGERATION_TABLES = {
    "refrigeration_equipment",
    "equipment_images",
    "refrigeration_layout_drafts",
    "refrigeration_layout_revisions",
}


def test_refrigeration_models_are_registered() -> None:
    register_models()
    assert REFRIGERATION_TABLES <= set(Base.metadata.tables)


def test_alembic_migration_created_refrigeration_schema() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url, "DATABASE_URL is required for migration validation"

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert REFRIGERATION_TABLES <= set(inspector.get_table_names())

        equipment_unique = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints("refrigeration_equipment")
        }
        assert equipment_unique["uq_refrigeration_equipment_organization_code"] == (
            "organization_id",
            "code",
        )
        equipment_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_equipment")
        }
        assert "fk_refrigeration_equipment_organization" in equipment_foreign_keys
        equipment_checks = {
            item["name"] for item in inspector.get_check_constraints("refrigeration_equipment")
        }
        assert {
            "ck_refrigeration_equipment_status",
            "ck_refrigeration_equipment_version_positive",
            "ck_refrigeration_equipment_online_non_negative",
            "ck_refrigeration_equipment_total_non_negative",
            "ck_refrigeration_equipment_online_within_total",
            "ck_refrigeration_equipment_alarms_non_negative",
        } <= equipment_checks

        draft_unique = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints("refrigeration_layout_drafts")
        }
        assert draft_unique["uq_refrigeration_layout_draft_equipment"] == (
            "organization_id",
            "equipment_id",
        )

        revision_unique = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints("refrigeration_layout_revisions")
        }
        assert revision_unique["uq_refrigeration_layout_revision_equipment"] == (
            "organization_id",
            "equipment_id",
            "revision",
        )

        draft_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_layout_drafts")
        }
        revision_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_layout_revisions")
        }
        image_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("equipment_images")
        }
        assert {
            "fk_layout_draft_image_id",
            "fk_refrigeration_layout_draft_organization",
        } <= draft_foreign_keys
        assert {
            "fk_layout_revision_image_id",
            "fk_refrigeration_layout_revision_organization",
        } <= revision_foreign_keys
        assert "fk_equipment_images_organization" in image_foreign_keys

        image_checks = {
            item["name"] for item in inspector.get_check_constraints("equipment_images")
        }
        assert {
            "ck_equipment_images_size_positive",
            "ck_equipment_images_width_positive",
            "ck_equipment_images_height_positive",
        } <= image_checks
    finally:
        engine.dispose()
