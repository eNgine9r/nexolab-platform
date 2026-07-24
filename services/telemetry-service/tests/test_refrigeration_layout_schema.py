from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect

from app.db import Base
from app.model_registry import register_models


REFRIGERATION_TABLES = {
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

        draft_unique = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints("refrigeration_layout_drafts")
        }
        assert draft_unique["uq_refrigeration_layout_draft_equipment"] == ("equipment_id",)

        revision_unique = {
            item["name"]: tuple(item["column_names"])
            for item in inspector.get_unique_constraints("refrigeration_layout_revisions")
        }
        assert revision_unique["uq_refrigeration_layout_revision_equipment"] == (
            "equipment_id",
            "revision",
        )

        draft_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_layout_drafts")
        }
        revision_foreign_keys = {
            item["name"] for item in inspector.get_foreign_keys("refrigeration_layout_revisions")
        }
        assert "fk_layout_draft_image_id" in draft_foreign_keys
        assert "fk_layout_revision_image_id" in revision_foreign_keys

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
