from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.domain import (
    AlertCondition,
    AlertObservation,
    AlertRecord,
    AlertRule,
    AlertState,
    AlertTransition,
    RuleRuntime,
    acknowledge_alert,
    close_alert,
    evaluate_observation,
)
from app.alerts.models import (
    AlertEventModel,
    AlertModel,
    AlertRuleModel,
    AlertRuleRuntimeModel,
)
from app.contracts import TelemetryEvent
from app.db import Database
from app.security.dependencies import AuthorizedRequest
from app.security.repository import AuditEventInput, SecurityRepository


class AlertRepositoryError(RuntimeError):
    code = "alert_repository_error"


class AlertRuleConflictError(AlertRepositoryError):
    code = "alert_rule_conflict"


class AlertNotFoundError(AlertRepositoryError):
    code = "alert_not_found"


class AlertStateConflictError(AlertRepositoryError):
    code = "alert_state_conflict"


@dataclass(frozen=True, slots=True)
class CreateAlertRuleInput:
    organization_id: str
    name: str
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    condition: AlertCondition
    severity: str
    trigger_threshold: float | None = None
    clear_threshold: float | None = None
    target_quality: str | None = None
    minimum_duration_seconds: int = 0
    cooldown_seconds: int = 0


class AlertRepository:
    def __init__(
        self,
        database: Database,
        security_repository: SecurityRepository,
    ) -> None:
        self._engine = database.engine
        self._security_repository = security_repository

    def create_rule(
        self,
        input: CreateAlertRuleInput,
        *,
        actor: AuthorizedRequest,
        reason: str | None = None,
    ) -> AlertRuleModel:
        rule_id = str(uuid4())
        rule = AlertRule(
            id=rule_id,
            organization_id=input.organization_id,
            node_id=input.node_id,
            equipment_id=input.equipment_id,
            channel_id=input.channel_id,
            metric=input.metric,
            condition=input.condition,
            severity=input.severity,
            trigger_threshold=input.trigger_threshold,
            clear_threshold=input.clear_threshold,
            target_quality=input.target_quality,
            minimum_duration_seconds=input.minimum_duration_seconds,
            cooldown_seconds=input.cooldown_seconds,
        )
        row = AlertRuleModel(
            id=rule.id,
            organization_id=rule.organization_id,
            name=_required_text(input.name, "name", 255),
            enabled=True,
            node_id=rule.node_id,
            equipment_id=rule.equipment_id,
            channel_id=rule.channel_id,
            metric=rule.metric,
            condition=rule.condition.value,
            severity=rule.severity,
            trigger_threshold=rule.trigger_threshold,
            clear_threshold=rule.clear_threshold,
            target_quality=rule.target_quality,
            minimum_duration_seconds=rule.minimum_duration_seconds,
            cooldown_seconds=rule.cooldown_seconds,
            created_by=actor.principal.subject,
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    session.add(row)
                    session.flush()
                    session.add(AlertRuleRuntimeModel(rule_id=row.id))
                    self._security_repository.append_audit_event(
                        AuditEventInput(
                            organization_id=row.organization_id,
                            actor_identity_id=actor.identity_id,
                            actor_subject=actor.principal.subject,
                            actor_roles=actor.principal.roles,
                            action="alert.rule.created",
                            entity_type="alert_rule",
                            entity_id=row.id,
                            after_snapshot=serialize_rule(row),
                            reason=_optional_text(reason, 1024),
                        ),
                        session=session,
                    )
                session.expunge(row)
                return row
        except IntegrityError as error:
            raise AlertRuleConflictError(
                f"alert rule name {row.name!r} already exists in organization"
            ) from error

    def list_rules(
        self,
        *,
        organization_id: str,
        enabled: bool | None = None,
    ) -> list[AlertRuleModel]:
        statement = (
            select(AlertRuleModel)
            .where(AlertRuleModel.organization_id == organization_id)
            .order_by(AlertRuleModel.name, AlertRuleModel.id)
        )
        if enabled is not None:
            statement = statement.where(AlertRuleModel.enabled.is_(enabled))
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            for row in rows:
                session.expunge(row)
            return rows

    def evaluate_payload(self, payload: dict[str, Any]) -> int:
        try:
            event = TelemetryEvent.model_validate(payload)
        except ValidationError as error:
            raise ValueError("persisted telemetry payload is invalid") from error

        with Session(self._engine) as session:
            with session.begin():
                rules = list(
                    session.scalars(
                        select(AlertRuleModel).where(
                            AlertRuleModel.enabled.is_(True),
                            AlertRuleModel.node_id == event.node_id,
                            AlertRuleModel.equipment_id == event.equipment_id,
                            AlertRuleModel.channel_id == event.channel_id,
                            AlertRuleModel.metric == event.metric,
                        )
                    )
                )
                changed = 0
                for rule_row in rules:
                    if self._evaluate_rule(session, rule_row, event):
                        changed += 1
                return changed

    def list_alerts(
        self,
        *,
        organization_id: str,
        states: Iterable[AlertState] | None = None,
        limit: int = 100,
    ) -> list[AlertModel]:
        statement = (
            select(AlertModel)
            .where(AlertModel.organization_id == organization_id)
            .order_by(AlertModel.triggered_at.desc(), AlertModel.id.desc())
            .limit(limit)
        )
        resolved_states = tuple(item.value for item in states or ())
        if resolved_states:
            statement = statement.where(AlertModel.state.in_(resolved_states))
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(session.scalars(statement))
            for row in rows:
                session.expunge(row)
            return rows

    def get_alert(
        self,
        *,
        organization_id: str,
        alert_id: str,
    ) -> AlertModel:
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.scalar(
                select(AlertModel).where(
                    AlertModel.id == alert_id,
                    AlertModel.organization_id == organization_id,
                )
            )
            if row is None:
                raise AlertNotFoundError(f"alert {alert_id!r} was not found")
            session.expunge(row)
            return row

    def list_events(
        self,
        *,
        organization_id: str,
        alert_id: str,
    ) -> list[AlertEventModel]:
        self.get_alert(organization_id=organization_id, alert_id=alert_id)
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(AlertEventModel)
                    .where(
                        AlertEventModel.organization_id == organization_id,
                        AlertEventModel.alert_id == alert_id,
                    )
                    .order_by(
                        AlertEventModel.occurred_at,
                        AlertEventModel.id,
                    )
                )
            )
            for row in rows:
                session.expunge(row)
            return rows

    def acknowledge(
        self,
        *,
        organization_id: str,
        alert_id: str,
        actor: AuthorizedRequest,
        reason: str,
        now: datetime | None = None,
    ) -> AlertModel:
        acknowledged_at = now or datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.scalar(
                    select(AlertModel)
                    .where(
                        AlertModel.id == alert_id,
                        AlertModel.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise AlertNotFoundError(f"alert {alert_id!r} was not found")
                before = serialize_alert(row)
                try:
                    updated = acknowledge_alert(
                        _record_from_row(row),
                        actor_subject=actor.principal.subject,
                        reason=reason,
                        acknowledged_at=acknowledged_at,
                    )
                except ValueError as error:
                    raise AlertStateConflictError(str(error)) from error
                _copy_record(row, updated)
                event = _append_event(
                    session,
                    row=row,
                    event_type=AlertTransition.ACKNOWLEDGED.value,
                    occurred_at=acknowledged_at,
                    actor_subject=actor.principal.subject,
                    reason=updated.acknowledgement_reason,
                )
                self._security_repository.append_audit_event(
                    AuditEventInput(
                        organization_id=organization_id,
                        actor_identity_id=actor.identity_id,
                        actor_subject=actor.principal.subject,
                        actor_roles=actor.principal.roles,
                        action="alert.acknowledged",
                        entity_type="alert",
                        entity_id=row.id,
                        before_snapshot=before,
                        after_snapshot=serialize_alert(row),
                        reason=updated.acknowledgement_reason,
                        request_id=event.id,
                    ),
                    session=session,
                )
            session.expunge(row)
            return row

    def close(
        self,
        *,
        organization_id: str,
        alert_id: str,
        actor: AuthorizedRequest,
        reason: str,
        now: datetime | None = None,
    ) -> AlertModel:
        closed_at = now or datetime.now(UTC)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.scalar(
                    select(AlertModel)
                    .where(
                        AlertModel.id == alert_id,
                        AlertModel.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if row is None:
                    raise AlertNotFoundError(f"alert {alert_id!r} was not found")
                before = serialize_alert(row)
                try:
                    updated = close_alert(
                        _record_from_row(row),
                        actor_subject=actor.principal.subject,
                        reason=reason,
                        closed_at=closed_at,
                    )
                except ValueError as error:
                    raise AlertStateConflictError(str(error)) from error
                _copy_record(row, updated)
                event = _append_event(
                    session,
                    row=row,
                    event_type=AlertTransition.CLOSED.value,
                    occurred_at=closed_at,
                    actor_subject=actor.principal.subject,
                    reason=updated.close_reason,
                )
                self._security_repository.append_audit_event(
                    AuditEventInput(
                        organization_id=organization_id,
                        actor_identity_id=actor.identity_id,
                        actor_subject=actor.principal.subject,
                        actor_roles=actor.principal.roles,
                        action="alert.closed",
                        entity_type="alert",
                        entity_id=row.id,
                        before_snapshot=before,
                        after_snapshot=serialize_alert(row),
                        reason=updated.close_reason,
                        request_id=event.id,
                    ),
                    session=session,
                )
            session.expunge(row)
            return row

    def _evaluate_rule(
        self,
        session: Session,
        rule_row: AlertRuleModel,
        event: TelemetryEvent,
    ) -> bool:
        runtime_row = session.scalar(
            select(AlertRuleRuntimeModel)
            .where(AlertRuleRuntimeModel.rule_id == rule_row.id)
            .with_for_update()
        )
        if runtime_row is None:
            runtime_row = AlertRuleRuntimeModel(rule_id=rule_row.id)
            session.add(runtime_row)
            session.flush()
        active_row = session.scalar(
            select(AlertModel)
            .where(
                AlertModel.rule_id == rule_row.id,
                AlertModel.state.in_(
                    (AlertState.ACTIVE.value, AlertState.ACKNOWLEDGED.value)
                ),
            )
            .with_for_update()
        )
        runtime = RuleRuntime(
            pending_since=_aware(runtime_row.pending_since),
            pending_event_id=runtime_row.pending_event_id,
            cooldown_until=_aware(runtime_row.cooldown_until),
            last_event_id=runtime_row.last_event_id,
            last_observed_at=_aware(runtime_row.last_observed_at),
            active_alert=_record_from_row(active_row) if active_row is not None else None,
        )
        rule = _rule_from_row(rule_row)
        observation = AlertObservation(
            event_id=str(event.event_id),
            captured_at=event.captured_at,
            value=event.value,
            quality=event.quality,
        )
        result = evaluate_observation(
            rule,
            observation,
            runtime,
            create_alert_id=lambda: str(uuid4()),
        )
        _copy_runtime(runtime_row, result.runtime)

        if AlertTransition.ACTIVATED in result.transitions:
            assert result.runtime.active_alert is not None
            row = _row_from_record(rule_row, result.runtime.active_alert)
            session.add(row)
            session.flush()
            _append_event(
                session,
                row=row,
                event_type=AlertTransition.ACTIVATED.value,
                telemetry_event_id=observation.event_id,
                occurred_at=observation.captured_at,
            )
            return True

        if active_row is not None and result.runtime.active_alert is not None:
            _copy_record(active_row, result.runtime.active_alert)

        if result.completed_alert is not None:
            assert active_row is not None
            _copy_record(active_row, result.completed_alert)
            _append_event(
                session,
                row=active_row,
                event_type=AlertTransition.RESOLVED.value,
                telemetry_event_id=observation.event_id,
                occurred_at=observation.captured_at,
            )
            return True

        return bool(result.transitions)


def serialize_rule(row: AlertRuleModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "enabled": row.enabled,
        "node_id": row.node_id,
        "equipment_id": row.equipment_id,
        "channel_id": row.channel_id,
        "metric": row.metric,
        "condition": row.condition,
        "severity": row.severity,
        "trigger_threshold": row.trigger_threshold,
        "clear_threshold": row.clear_threshold,
        "target_quality": row.target_quality,
        "minimum_duration_seconds": row.minimum_duration_seconds,
        "cooldown_seconds": row.cooldown_seconds,
        "created_by": row.created_by,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def serialize_alert(row: AlertModel) -> dict[str, Any]:
    end = row.resolved_at or row.last_observed_at
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "rule_id": row.rule_id,
        "state": row.state,
        "severity": row.severity,
        "node_id": row.node_id,
        "equipment_id": row.equipment_id,
        "channel_id": row.channel_id,
        "metric": row.metric,
        "triggered_at": _iso(row.triggered_at),
        "first_event_id": row.first_event_id,
        "last_event_id": row.last_event_id,
        "trigger_value": row.trigger_value,
        "current_value": row.current_value,
        "peak_value": row.peak_value,
        "current_quality": row.current_quality,
        "last_observed_at": _iso(row.last_observed_at),
        "duration_seconds": max(
            0.0,
            (_aware(end) - _aware(row.triggered_at)).total_seconds(),
        ),
        "acknowledged_at": _iso(row.acknowledged_at),
        "acknowledged_by": row.acknowledged_by,
        "acknowledgement_reason": row.acknowledgement_reason,
        "resolved_at": _iso(row.resolved_at),
        "closed_at": _iso(row.closed_at),
        "closed_by": row.closed_by,
        "close_reason": row.close_reason,
    }


def serialize_event(row: AlertEventModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "alert_id": row.alert_id,
        "rule_id": row.rule_id,
        "event_type": row.event_type,
        "telemetry_event_id": row.telemetry_event_id,
        "actor_subject": row.actor_subject,
        "reason": row.reason,
        "payload": row.payload,
        "occurred_at": _iso(row.occurred_at),
    }


def _rule_from_row(row: AlertRuleModel) -> AlertRule:
    return AlertRule(
        id=row.id,
        organization_id=row.organization_id,
        node_id=row.node_id,
        equipment_id=row.equipment_id,
        channel_id=row.channel_id,
        metric=row.metric,
        condition=AlertCondition(row.condition),
        severity=row.severity,
        trigger_threshold=row.trigger_threshold,
        clear_threshold=row.clear_threshold,
        target_quality=row.target_quality,
        minimum_duration_seconds=row.minimum_duration_seconds,
        cooldown_seconds=row.cooldown_seconds,
    )


def _record_from_row(row: AlertModel) -> AlertRecord:
    return AlertRecord(
        id=row.id,
        rule_id=row.rule_id,
        state=AlertState(row.state),
        triggered_at=_aware(row.triggered_at),
        first_event_id=row.first_event_id,
        last_event_id=row.last_event_id,
        trigger_value=row.trigger_value,
        current_value=row.current_value,
        peak_value=row.peak_value,
        current_quality=row.current_quality,
        last_observed_at=_aware(row.last_observed_at),
        acknowledged_at=_aware(row.acknowledged_at),
        acknowledged_by=row.acknowledged_by,
        acknowledgement_reason=row.acknowledgement_reason,
        resolved_at=_aware(row.resolved_at),
        closed_at=_aware(row.closed_at),
        closed_by=row.closed_by,
        close_reason=row.close_reason,
    )


def _row_from_record(rule: AlertRuleModel, record: AlertRecord) -> AlertModel:
    return AlertModel(
        id=record.id,
        organization_id=rule.organization_id,
        rule_id=rule.id,
        state=record.state.value,
        severity=rule.severity,
        node_id=rule.node_id,
        equipment_id=rule.equipment_id,
        channel_id=rule.channel_id,
        metric=rule.metric,
        triggered_at=record.triggered_at,
        first_event_id=record.first_event_id,
        last_event_id=record.last_event_id,
        trigger_value=record.trigger_value,
        current_value=record.current_value,
        peak_value=record.peak_value,
        current_quality=record.current_quality,
        last_observed_at=record.last_observed_at,
    )


def _copy_record(row: AlertModel, record: AlertRecord) -> None:
    row.state = record.state.value
    row.last_event_id = record.last_event_id
    row.current_value = record.current_value
    row.peak_value = record.peak_value
    row.current_quality = record.current_quality
    row.last_observed_at = record.last_observed_at
    row.acknowledged_at = record.acknowledged_at
    row.acknowledged_by = record.acknowledged_by
    row.acknowledgement_reason = record.acknowledgement_reason
    row.resolved_at = record.resolved_at
    row.closed_at = record.closed_at
    row.closed_by = record.closed_by
    row.close_reason = record.close_reason


def _copy_runtime(row: AlertRuleRuntimeModel, runtime: RuleRuntime) -> None:
    row.pending_since = runtime.pending_since
    row.pending_event_id = runtime.pending_event_id
    row.cooldown_until = runtime.cooldown_until
    row.last_event_id = runtime.last_event_id
    row.last_observed_at = runtime.last_observed_at


def _append_event(
    session: Session,
    *,
    row: AlertModel,
    event_type: str,
    occurred_at: datetime,
    telemetry_event_id: str | None = None,
    actor_subject: str | None = None,
    reason: str | None = None,
) -> AlertEventModel:
    event = AlertEventModel(
        id=str(uuid4()),
        organization_id=row.organization_id,
        alert_id=row.id,
        rule_id=row.rule_id,
        event_type=event_type,
        telemetry_event_id=telemetry_event_id,
        actor_subject=actor_subject,
        reason=reason,
        payload=serialize_alert(row),
        occurred_at=occurred_at,
    )
    session.add(event)
    session.flush()
    return event


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def _required_text(value: str, name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized[:maximum]


def _optional_text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:maximum] or None
