from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.alerts.domain import (
    AlertCondition,
    AlertEvaluationDecision,
    AlertEvaluationSnapshot,
    AlertRuleConfiguration,
    AlertState,
    TelemetryObservation,
)
from app.alerts.evaluator import evaluate_threshold
from app.alerts.models import (
    AlertEvaluationState,
    AlertEvidenceSample,
    AlertInstance,
    AlertRule,
    AlertRuleVersion,
    AlertTransition,
)
from app.contracts import TelemetryEvent
from app.db import Database
from app.sessions.models import TestSession
from app.sessions.telemetry_attribution import TelemetrySessionContext


SYSTEM_ACTOR_ID = "nexolab-alert-engine"
SYSTEM_ACTOR_SOURCE = "system"


@dataclass(frozen=True, slots=True)
class PersistedTelemetryContext:
    organization_id: str
    session_id: str | None
    stage_id: str | None
    binding_id: str | None
    config_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class AlertProcessingResult:
    matched_rules: int
    decisions: tuple[AlertEvaluationDecision, ...]


class AlertProcessor:
    """Evaluate committed telemetry against organization-scoped alert rules."""

    def __init__(
        self,
        database: Database,
        *,
        default_organization_id: str,
    ) -> None:
        self._engine = database.engine
        self._default_organization_id = default_organization_id.strip()
        if not self._default_organization_id:
            raise ValueError("default_organization_id is required")

    def process_payload(self, payload: dict[str, Any]) -> AlertProcessingResult:
        event = TelemetryEvent.model_validate(payload)
        observation = TelemetryObservation(
            event_id=str(event.event_id),
            captured_at=event.captured_at,
            value=event.value,
        )
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                context = self._context_for_event(session, event, payload)
                records = self._matching_rules(session, event, context)
                decisions = tuple(
                    self._evaluate_rule(
                        session,
                        rule,
                        version,
                        event,
                        observation,
                        context,
                    )
                    for rule, version in records
                )
        return AlertProcessingResult(
            matched_rules=len(records),
            decisions=decisions,
        )

    def _context_for_event(
        self,
        session: Session,
        event: TelemetryEvent,
        payload: dict[str, Any],
    ) -> PersistedTelemetryContext:
        row = session.execute(
            select(
                TelemetrySessionContext.session_id,
                TelemetrySessionContext.stage_id,
                TelemetrySessionContext.binding_id,
                TelemetrySessionContext.config_snapshot_id,
                TestSession.organization_id,
            )
            .join(
                TestSession,
                TestSession.id == TelemetrySessionContext.session_id,
            )
            .where(
                TelemetrySessionContext.telemetry_event_id == str(event.event_id)
            )
        ).mappings().first()
        if row is not None:
            return PersistedTelemetryContext(
                organization_id=str(row["organization_id"]),
                session_id=str(row["session_id"]),
                stage_id=(str(row["stage_id"]) if row["stage_id"] is not None else None),
                binding_id=str(row["binding_id"]),
                config_snapshot_id=str(row["config_snapshot_id"]),
            )

        organization_id = payload.get("organization_id")
        if not isinstance(organization_id, str) or not organization_id.strip():
            organization_id = self._default_organization_id
        return PersistedTelemetryContext(
            organization_id=organization_id.strip(),
            session_id=None,
            stage_id=None,
            binding_id=None,
            config_snapshot_id=None,
        )

    @staticmethod
    def _matching_rules(
        session: Session,
        event: TelemetryEvent,
        context: PersistedTelemetryContext,
    ) -> list[tuple[AlertRule, AlertRuleVersion]]:
        session_filter = (
            AlertRule.session_id.is_(None)
            if context.session_id is None
            else or_(
                AlertRule.session_id.is_(None),
                AlertRule.session_id == context.session_id,
            )
        )
        statement = (
            select(AlertRule, AlertRuleVersion)
            .join(
                AlertRuleVersion,
                (AlertRuleVersion.rule_id == AlertRule.id)
                & (AlertRuleVersion.version == AlertRule.current_version),
            )
            .where(
                AlertRule.organization_id == context.organization_id,
                AlertRule.enabled.is_(True),
                AlertRule.metric == event.metric,
                or_(AlertRule.node_id.is_(None), AlertRule.node_id == event.node_id),
                or_(
                    AlertRule.equipment_id.is_(None),
                    AlertRule.equipment_id == event.equipment_id,
                ),
                or_(
                    AlertRule.channel_id.is_(None),
                    AlertRule.channel_id == event.channel_id,
                ),
                session_filter,
            )
            .order_by(AlertRule.id)
        )
        return [(rule, version) for rule, version in session.execute(statement)]

    def _evaluate_rule(
        self,
        session: Session,
        rule: AlertRule,
        version: AlertRuleVersion,
        event: TelemetryEvent,
        observation: TelemetryObservation,
        context: PersistedTelemetryContext,
    ) -> AlertEvaluationDecision:
        resource_key = _resource_key(event, context)
        state = session.scalar(
            select(AlertEvaluationState)
            .where(
                AlertEvaluationState.rule_id == rule.id,
                AlertEvaluationState.resource_key == resource_key,
            )
            .with_for_update()
        )
        if state is None:
            state = AlertEvaluationState(
                id=str(uuid4()),
                organization_id=context.organization_id,
                rule_id=rule.id,
                resource_key=resource_key,
                maximum_deviation=0.0,
                updated_at=event.captured_at,
            )
            session.add(state)

        snapshot = AlertEvaluationSnapshot(
            last_event_id=state.last_event_id,
            last_captured_at=_as_utc(state.last_captured_at),
            trigger_pending_since=_as_utc(state.trigger_pending_since),
            clear_pending_since=_as_utc(state.clear_pending_since),
            active_alert_id=state.active_alert_id,
            cooldown_until=_as_utc(state.cooldown_until),
            last_value=state.last_value,
            maximum_deviation=state.maximum_deviation,
        )
        configuration = AlertRuleConfiguration(
            condition=AlertCondition(version.condition),
            trigger_threshold=version.trigger_threshold,
            clear_threshold=version.clear_threshold,
            minimum_duration_seconds=version.minimum_duration_seconds,
            clear_duration_seconds=version.clear_duration_seconds,
            debounce_seconds=version.debounce_seconds,
            cooldown_seconds=version.cooldown_seconds,
        )
        result = evaluate_threshold(configuration, snapshot, observation)
        if result.decision in {
            AlertEvaluationDecision.IGNORE_DUPLICATE,
            AlertEvaluationDecision.IGNORE_OUT_OF_ORDER,
        }:
            return result.decision

        active_alert = self._active_alert(session, state.active_alert_id)
        previous_maximum = snapshot.maximum_deviation
        next_snapshot = result.snapshot

        if result.decision is AlertEvaluationDecision.TRIGGER:
            alert_id = str(uuid4())
            active_alert = AlertInstance(
                id=alert_id,
                organization_id=context.organization_id,
                rule_id=rule.id,
                rule_version_id=version.id,
                resource_key=resource_key,
                node_id=event.node_id,
                equipment_id=event.equipment_id,
                channel_id=event.channel_id,
                metric=event.metric,
                state=AlertState.ACTIVE.value,
                severity=rule.severity,
                trigger_value=event.value,
                trigger_threshold=version.trigger_threshold,
                clear_threshold=version.clear_threshold,
                maximum_deviation=result.snapshot.maximum_deviation,
                first_event_id=str(event.event_id),
                last_event_id=str(event.event_id),
                session_id=context.session_id,
                stage_id=context.stage_id,
                binding_id=context.binding_id,
                context={
                    "config_snapshot_id": context.config_snapshot_id,
                    "unit": event.unit,
                    "quality": event.quality,
                    "source": event.source,
                },
                triggered_at=event.captured_at,
                lock_version=1,
                created_at=event.captured_at,
                updated_at=event.captured_at,
            )
            session.add(active_alert)
            # AlertEvaluationState.active_alert_id has an explicit FK but no ORM
            # relationship, so persist the alert before updating that state.
            session.flush([active_alert])
            session.add(
                _system_transition(
                    active_alert,
                    event_type="alert_triggered",
                    previous_state=None,
                    next_state=AlertState.ACTIVE,
                    event=event,
                    payload={
                        "rule_id": rule.id,
                        "rule_version": version.version,
                        "trigger_threshold": version.trigger_threshold,
                    },
                )
            )
            session.add(
                _evidence(
                    active_alert,
                    event,
                    threshold=version.trigger_threshold,
                    deviation=result.deviation,
                    reason="triggered",
                )
            )
            next_snapshot = replace(next_snapshot, active_alert_id=alert_id)

        elif active_alert is not None:
            active_alert.last_event_id = str(event.event_id)
            active_alert.maximum_deviation = max(
                active_alert.maximum_deviation,
                result.snapshot.maximum_deviation,
            )
            active_alert.updated_at = event.captured_at
            if _should_capture_evidence(
                result.decision,
                result.deviation,
                previous_maximum,
            ):
                threshold = (
                    version.clear_threshold
                    if result.decision
                    in {
                        AlertEvaluationDecision.START_CLEAR_PENDING,
                        AlertEvaluationDecision.RESET_CLEAR_PENDING,
                        AlertEvaluationDecision.RESOLVE,
                    }
                    else version.trigger_threshold
                )
                session.add(
                    _evidence(
                        active_alert,
                        event,
                        threshold=threshold,
                        deviation=result.deviation,
                        reason=result.decision.value,
                    )
                )

            if result.decision is AlertEvaluationDecision.RESOLVE:
                previous_state = AlertState(active_alert.state)
                active_alert.state = AlertState.RESOLVED.value
                active_alert.resolved_at = event.captured_at
                active_alert.lock_version += 1
                session.add(
                    _system_transition(
                        active_alert,
                        event_type="alert_resolved",
                        previous_state=previous_state,
                        next_state=AlertState.RESOLVED,
                        event=event,
                        payload={
                            "clear_threshold": version.clear_threshold,
                            "maximum_deviation": active_alert.maximum_deviation,
                        },
                    )
                )
                # A resolved alert remains the non-closed instance until an
                # authorized operator closes it. Cooldown is preserved.
                next_snapshot = replace(
                    next_snapshot,
                    active_alert_id=active_alert.id,
                )

        self._apply_snapshot(state, next_snapshot, event.captured_at)
        return result.decision

    @staticmethod
    def _active_alert(
        session: Session,
        alert_id: str | None,
    ) -> AlertInstance | None:
        if alert_id is None:
            return None
        return session.scalar(
            select(AlertInstance)
            .where(AlertInstance.id == alert_id)
            .with_for_update()
        )

    @staticmethod
    def _apply_snapshot(
        state: AlertEvaluationState,
        snapshot: AlertEvaluationSnapshot,
        updated_at: datetime,
    ) -> None:
        state.last_event_id = snapshot.last_event_id
        state.last_captured_at = snapshot.last_captured_at
        state.trigger_pending_since = snapshot.trigger_pending_since
        state.clear_pending_since = snapshot.clear_pending_since
        state.active_alert_id = snapshot.active_alert_id
        state.cooldown_until = snapshot.cooldown_until
        state.last_value = snapshot.last_value
        state.maximum_deviation = snapshot.maximum_deviation
        state.updated_at = updated_at


def _resource_key(
    event: TelemetryEvent,
    context: PersistedTelemetryContext,
) -> str:
    return "|".join(
        (
            context.organization_id,
            context.session_id or "-",
            event.node_id,
            event.equipment_id,
            event.channel_id,
            event.metric,
        )
    )


def _system_transition(
    alert: AlertInstance,
    *,
    event_type: str,
    previous_state: AlertState | None,
    next_state: AlertState,
    event: TelemetryEvent,
    payload: dict[str, Any],
) -> AlertTransition:
    return AlertTransition(
        id=str(uuid4()),
        alert_id=alert.id,
        event_type=event_type,
        previous_state=(previous_state.value if previous_state is not None else None),
        next_state=next_state.value,
        actor_id=SYSTEM_ACTOR_ID,
        actor_source=SYSTEM_ACTOR_SOURCE,
        reason=None,
        idempotency_key=f"{event_type}:{event.event_id}",
        payload=payload,
        occurred_at=event.captured_at,
    )


def _evidence(
    alert: AlertInstance,
    event: TelemetryEvent,
    *,
    threshold: float,
    deviation: float,
    reason: str,
) -> AlertEvidenceSample:
    return AlertEvidenceSample(
        id=str(uuid4()),
        alert_id=alert.id,
        event_id=str(event.event_id),
        captured_at=event.captured_at,
        value=event.value,
        threshold=threshold,
        deviation=deviation,
        payload={
            "reason": reason,
            "quality": event.quality,
            "unit": event.unit,
            "alarm": event.alarm,
        },
    )


def _should_capture_evidence(
    decision: AlertEvaluationDecision,
    deviation: float,
    previous_maximum: float,
) -> bool:
    return (
        decision
        in {
            AlertEvaluationDecision.START_CLEAR_PENDING,
            AlertEvaluationDecision.RESET_CLEAR_PENDING,
            AlertEvaluationDecision.RESOLVE,
        }
        or deviation > previous_maximum
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
