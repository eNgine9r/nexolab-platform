from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.model_registry import register_models
from app.sessions.audit_repository import AuditedSessionRepository
from app.sessions.models import AuditLog, SessionEvent
from app.sessions.schemas import SessionCreate
from app.sessions.telemetry_attribution import SessionAwareDatabase


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for trigger validation",
)


def test_postgres_session_events_and_audit_log_are_append_only() -> None:
    register_models()
    database = SessionAwareDatabase(os.environ["DATABASE_URL"])
    repository = AuditedSessionRepository(database)
    suffix = str(uuid4())
    payload = SessionCreate(
        session_number=f"NXL-AUDIT-PG-{suffix}",
        title="PostgreSQL audit trigger test",
        test_object="K106",
        node_id="edge-01",
        actor_id="operator-1",
        actor_source="test",
        occurred_at=datetime.now(UTC),
        reason="Verify append-only database enforcement",
    )

    try:
        result = repository.create(
            payload,
            idempotency_key=f"postgres-audit-trigger-{suffix}",
        )
        with Session(database.engine) as db_session:
            audit_id = db_session.scalar(
                select(AuditLog.id).where(
                    AuditLog.session_event_id == result.event.id
                )
            )
        assert audit_id is not None

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE session_events SET reason = 'tampered' "
                        "WHERE id = :event_id"
                    ),
                    {"event_id": result.event.id},
                )
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM audit_log WHERE id = :audit_id"),
                    {"audit_id": audit_id},
                )

        with Session(database.engine) as db_session:
            assert db_session.get(SessionEvent, result.event.id) is not None
            assert db_session.get(AuditLog, audit_id) is not None
    finally:
        database.dispose()
