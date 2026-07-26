from __future__ import annotations

from typing import Any

from sqlalchemy import DDL, event, inspect, update
from sqlalchemy.orm import Session

from app.alerts.models import (
    AlertEvaluationState,
    AlertEvidenceSample,
    AlertInstance,
    AlertRuleVersion,
    AlertTransition,
)
from app.alerts.domain import AlertState


_registered = False


class AlertAuditMutationError(RuntimeError):
    pass


def register_alert_immutability() -> None:
    global _registered
    if _registered:
        return

    for model, table_name in (
        (AlertRuleVersion, "alert_rule_versions"),
        (AlertTransition, "alert_transitions"),
        (AlertEvidenceSample, "alert_evidence_samples"),
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

    event.listen(Session, "before_flush", _release_closed_alert_state)
    _registered = True


def _reject_mapper_mutation(
    _mapper: Any,
    _connection: Any,
    target: AlertRuleVersion | AlertTransition | AlertEvidenceSample,
) -> None:
    raise AlertAuditMutationError(
        f"{target.__class__.__name__} records are append-only"
    )


def _release_closed_alert_state(
    session: Session,
    _flush_context: Any,
    _instances: Any,
) -> None:
    for target in session.dirty:
        if not isinstance(target, AlertInstance):
            continue
        state_history = inspect(target).attrs.state.history
        if not state_history.has_changes() or target.state != AlertState.CLOSED.value:
            continue
        session.execute(
            update(AlertEvaluationState)
            .where(AlertEvaluationState.active_alert_id == target.id)
            .values(
                active_alert_id=None,
                trigger_pending_since=None,
                clear_pending_since=None,
                maximum_deviation=0.0,
            )
        )
