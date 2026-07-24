from __future__ import annotations

from typing import Any

from sqlalchemy import DDL, event

from app.sessions.models import AuditLog, SessionEvent


_registered = False


class AuditMutationError(RuntimeError):
    pass


def register_audit_immutability() -> None:
    global _registered
    if _registered:
        return

    event.listen(
        SessionEvent.__table__,
        "after_create",
        DDL(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_session_created_idempotency_key
            ON session_events(idempotency_key)
            WHERE event_type = 'session_created'
            """
        ).execute_if(dialect="sqlite"),
    )

    for model, table_name in (
        (SessionEvent, "session_events"),
        (AuditLog, "audit_log"),
    ):
        event.listen(model, "before_update", _reject_mapper_mutation)
        event.listen(model, "before_delete", _reject_mapper_mutation)
        event.listen(
            model.__table__,
            "after_create",
            DDL(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_append_only_update
                BEFORE UPDATE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            ).execute_if(dialect="sqlite"),
        )
        event.listen(
            model.__table__,
            "after_create",
            DDL(
                f"""
                CREATE TRIGGER IF NOT EXISTS trg_{table_name}_append_only_delete
                BEFORE DELETE ON {table_name}
                BEGIN
                    SELECT RAISE(ABORT, '{table_name} is append-only');
                END
                """
            ).execute_if(dialect="sqlite"),
        )

    _registered = True


def _reject_mapper_mutation(
    _mapper: Any,
    _connection: Any,
    target: SessionEvent | AuditLog,
) -> None:
    raise AuditMutationError(
        f"{target.__class__.__name__} records are append-only"
    )
