from __future__ import annotations

from typing import Any

from sqlalchemy import DDL, event

from app.daily_reports.models import RefrigerationDailyReportSnapshot

_registered = False


class DailyReportSnapshotMutationError(RuntimeError):
    pass


def register_daily_report_immutability() -> None:
    global _registered
    if _registered:
        return
    model = RefrigerationDailyReportSnapshot
    table_name = model.__tablename__
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
    target: RefrigerationDailyReportSnapshot,
) -> None:
    raise DailyReportSnapshotMutationError(
        f"{target.__class__.__name__} records are append-only"
    )
