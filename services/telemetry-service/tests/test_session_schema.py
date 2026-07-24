from __future__ import annotations

import os

from sqlalchemy import UniqueConstraint, create_engine, inspect

from app.db import Base, TelemetrySample
from app.model_registry import SESSION_MODEL_COUNT, register_models


SESSION_TABLES = {
    "test_sessions",
    "session_channel_bindings",
    "session_config_snapshots",
    "session_limits",
    "session_stages",
    "session_events",
    "session_stage_transitions",
    "session_notes",
    "audit_log",
}


def test_session_models_are_registered_without_changing_telemetry_shape() -> None:
    register_models()

    assert SESSION_MODEL_COUNT == len(SESSION_TABLES)
    assert SESSION_TABLES <= set(Base.metadata.tables)

    telemetry_columns = set(TelemetrySample.__table__.columns.keys())
    assert telemetry_columns == {
        "id",
        "event_id",
        "node_id",
        "captured_at",
        "metric",
        "value",
        "unit",
        "quality",
        "source",
        "equipment_id",
        "channel_id",
        "alarm",
        "raw_value",
        "raw_status",
        "raw_payload",
        "raw_payload_retained",
        "received_at",
    }


def test_session_event_idempotency_is_enforced_in_metadata() -> None:
    register_models()

    table = Base.metadata.tables["session_events"]
    unique_constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert unique_constraints["uq_session_event_idempotency_key"] == (
        "session_id",
        "idempotency_key",
    )


def test_active_channel_lease_and_limit_versions_use_partial_unique_indexes() -> None:
    register_models()

    binding_indexes = {
        index.name: index
        for index in Base.metadata.tables["session_channel_bindings"].indexes
    }
    lease_index = binding_indexes["uq_active_session_channel_lease"]

    assert lease_index.unique is True
    assert tuple(column.name for column in lease_index.columns) == (
        "node_id",
        "equipment_id",
        "channel_id",
        "metric",
    )
    assert "activated_at IS NOT NULL" in str(
        lease_index.dialect_options["postgresql"]["where"]
    )
    assert "released_at IS NULL" in str(
        lease_index.dialect_options["postgresql"]["where"]
    )

    limit_indexes = {
        index.name: index
        for index in Base.metadata.tables["session_limits"].indexes
    }
    assert limit_indexes["uq_session_binding_limit_version"].unique is True
    assert limit_indexes["uq_session_metric_limit_version"].unique is True


def test_alembic_migration_created_complete_session_schema() -> None:
    database_url = os.environ.get("DATABASE_URL")
    assert database_url, "DATABASE_URL is required for migration validation"

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())

        assert SESSION_TABLES <= tables
        assert {"telemetry_samples", "telemetry_dead_letters"} <= tables

        session_foreign_keys = {
            foreign_key["name"]
            for foreign_key in inspector.get_foreign_keys("test_sessions")
        }
        assert {
            "fk_test_sessions_current_stage_id",
            "fk_test_sessions_active_config_snapshot_id",
        } <= session_foreign_keys

        event_unique_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints("session_events")
        }
        assert event_unique_constraints["uq_session_event_idempotency_key"] == (
            "session_id",
            "idempotency_key",
        )

        binding_indexes = {
            index["name"]: index
            for index in inspector.get_indexes("session_channel_bindings")
        }
        assert binding_indexes["uq_active_session_channel_lease"]["unique"] is True

        stage_constraints = {
            constraint["name"]
            for constraint in inspector.get_check_constraints("session_stages")
        }
        assert {
            "ck_session_stage_sequence_nonnegative",
            "ck_session_stage_type",
            "ck_session_stage_exit_order",
        } <= stage_constraints
    finally:
        engine.dispose()
