from __future__ import annotations

import os

from sqlalchemy import create_engine, inspect

from app.db import Base
from app.model_registry import register_models


CONTEXT_TABLE = "telemetry_session_contexts"
EXPECTED_FOREIGN_KEYS = {
    "fk_telemetry_context_event_id",
    "fk_telemetry_context_session_id",
    "fk_telemetry_context_stage_id",
    "fk_telemetry_context_binding_id",
    "fk_telemetry_context_snapshot_id",
}
EXPECTED_INDEXES = {
    "ix_telemetry_context_session_captured",
    "ix_telemetry_context_session_stage_captured",
    "ix_telemetry_context_binding",
    "ix_telemetry_context_snapshot",
}


def test_telemetry_context_metadata_is_registered() -> None:
    register_models()

    table = Base.metadata.tables[CONTEXT_TABLE]
    assert tuple(column.name for column in table.primary_key.columns) == (
        "telemetry_event_id",
    )
    assert {foreign_key.name for foreign_key in table.foreign_key_constraints} == (
        EXPECTED_FOREIGN_KEYS
    )
    assert {index.name for index in table.indexes} == EXPECTED_INDEXES
    assert table.c.session_id.nullable is False
    assert table.c.binding_id.nullable is False
    assert table.c.config_snapshot_id.nullable is False
    assert table.c.stage_id.nullable is True


def test_alembic_created_telemetry_context_schema() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url, "DATABASE_URL is required for migration validation"

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        assert CONTEXT_TABLE in set(inspector.get_table_names())
        assert {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys(CONTEXT_TABLE)
        } == EXPECTED_FOREIGN_KEYS
        assert {
            index["name"]
            for index in inspector.get_indexes(CONTEXT_TABLE)
        } == EXPECTED_INDEXES
        assert inspector.get_pk_constraint(CONTEXT_TABLE)[
            "constrained_columns"
        ] == ["telemetry_event_id"]
    finally:
        engine.dispose()
