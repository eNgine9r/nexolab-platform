from __future__ import annotations

from typing import Any

from sqlalchemy import DDL, event

from app.auth.models import PlatformAuditEvent


_registered = False


class PlatformAuditMutationError(RuntimeError):
    pass


def register_platform_audit_immutability() -> None:
    global _registered
    if _registered:
        return

    event.listen(PlatformAuditEvent, "before_update", _reject_mutation)
    event.listen(PlatformAuditEvent, "before_delete", _reject_mutation)
    event.listen(
        PlatformAuditEvent.__table__,
        "after_create",
        DDL(
            """
            CREATE TRIGGER IF NOT EXISTS trg_platform_audit_events_append_only_update
            BEFORE UPDATE ON platform_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'platform_audit_events is append-only');
            END
            """
        ).execute_if(dialect="sqlite"),
    )
    event.listen(
        PlatformAuditEvent.__table__,
        "after_create",
        DDL(
            """
            CREATE TRIGGER IF NOT EXISTS trg_platform_audit_events_append_only_delete
            BEFORE DELETE ON platform_audit_events
            BEGIN
                SELECT RAISE(ABORT, 'platform_audit_events is append-only');
            END
            """
        ).execute_if(dialect="sqlite"),
    )
    _registered = True


def _reject_mutation(
    _mapper: Any,
    _connection: Any,
    _target: PlatformAuditEvent,
) -> None:
    raise PlatformAuditMutationError("PlatformAuditEvent records are append-only")
