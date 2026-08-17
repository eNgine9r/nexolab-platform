from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance, AlertTransition
from app.db import TelemetrySample
from app.reports.domain import AlertTransitionEvidenceRow, TelemetryEvidenceRow
from app.sessions.models import (
    AuditLog,
    SessionChannelBinding,
    SessionConfigSnapshot,
    SessionEvent,
    SessionLimit,
    SessionNote,
    SessionStage,
    TestSession,
)
from app.sessions.telemetry_attribution import TelemetrySessionContext
from app.sessions.time_utils import as_utc

REPORT_SOURCE_SCHEMA = "nexolab.report-source.v1"


@dataclass(frozen=True, slots=True)
class ReportSource:
    metadata: dict[str, Any]
    telemetry: list[TelemetryEvidenceRow]
    alert_transitions: list[AlertTransitionEvidenceRow]


def assemble_report_source(
    session: Session,
    test_session: TestSession,
    config_snapshot: SessionConfigSnapshot,
    *,
    selected_binding_ids: tuple[str, ...] | None = None,
    selection_mode: str = "all_session_bindings",
) -> ReportSource:
    evidence_binding_ids = (
        None if selection_mode == "all_session_bindings" else selected_binding_ids
    )
    bindings = _binding_payloads(
        session,
        test_session.id,
        selected_binding_ids=evidence_binding_ids,
    )
    effective_binding_ids = tuple(binding["id"] for binding in bindings)
    return ReportSource(
        metadata={
            "session": _session_payload(test_session),
            "configuration": _configuration_payload(config_snapshot),
            "telemetry_selection": {
                "mode": selection_mode,
                "binding_ids": list(effective_binding_ids),
                "binding_count": len(effective_binding_ids),
            },
            "bindings": bindings,
            "limits": _limit_payloads(
                session,
                test_session.id,
                selected_binding_ids=evidence_binding_ids,
            ),
            "stages": _stage_payloads(session, test_session.id),
            "notes": _note_payloads(session, test_session.id),
            "events": _event_payloads(session, test_session.id),
            "audit": _audit_payloads(session, test_session.id),
        },
        telemetry=_telemetry_rows(
            session,
            test_session.id,
            selected_binding_ids=evidence_binding_ids,
        ),
        alert_transitions=_alert_rows(
            session,
            test_session.id,
            selected_binding_ids=evidence_binding_ids,
        ),
    )


def _telemetry_rows(
    session: Session,
    session_id: str,
    *,
    selected_binding_ids: tuple[str, ...] | None = None,
) -> list[TelemetryEvidenceRow]:
    statement = (
        select(
            TelemetrySample.event_id,
            TelemetrySample.captured_at,
            TelemetrySample.node_id,
            TelemetrySample.equipment_id,
            TelemetrySample.channel_id,
            TelemetrySample.metric,
            TelemetrySample.value,
            TelemetrySample.unit,
            TelemetrySample.quality,
            TelemetrySample.alarm,
            TelemetrySample.source,
            TelemetrySessionContext.session_id,
            TelemetrySessionContext.stage_id,
            TelemetrySessionContext.binding_id,
            TelemetrySessionContext.config_snapshot_id,
        )
        .join(
            TelemetrySessionContext,
            TelemetrySessionContext.telemetry_event_id == TelemetrySample.event_id,
        )
        .where(TelemetrySessionContext.session_id == session_id)
    )
    if selected_binding_ids is not None:
        statement = statement.where(
            TelemetrySessionContext.binding_id.in_(selected_binding_ids)
        )
    rows = session.execute(
        statement.order_by(TelemetrySample.captured_at, TelemetrySample.event_id)
    ).all()
    return [
        TelemetryEvidenceRow(
            event_id=row.event_id,
            captured_at=as_utc(row.captured_at),
            node_id=row.node_id,
            equipment_id=row.equipment_id,
            channel_id=row.channel_id,
            metric=row.metric,
            value=row.value,
            unit=row.unit,
            quality=row.quality,
            alarm=row.alarm,
            source=row.source,
            session_id=row.session_id,
            stage_id=row.stage_id,
            binding_id=row.binding_id,
            config_snapshot_id=row.config_snapshot_id,
        )
        for row in rows
    ]


def _alert_rows(
    session: Session,
    session_id: str,
    *,
    selected_binding_ids: tuple[str, ...] | None = None,
) -> list[AlertTransitionEvidenceRow]:
    statement = (
        select(AlertInstance, AlertTransition)
        .join(AlertTransition, AlertTransition.alert_id == AlertInstance.id)
        .where(AlertInstance.session_id == session_id)
    )
    if selected_binding_ids is not None:
        statement = statement.where(
            or_(
                AlertInstance.binding_id.is_(None),
                AlertInstance.binding_id.in_(selected_binding_ids),
            )
        )
    rows = session.execute(
        statement.order_by(
            AlertTransition.occurred_at,
            AlertInstance.id,
            AlertTransition.id,
        )
    ).all()
    return [
        AlertTransitionEvidenceRow(
            alert_id=alert.id,
            transition_id=transition.id,
            rule_id=alert.rule_id,
            rule_version_id=alert.rule_version_id,
            event_type=transition.event_type,
            previous_state=transition.previous_state,
            next_state=transition.next_state,
            actor_id=transition.actor_id,
            actor_source=transition.actor_source,
            reason=transition.reason,
            occurred_at=as_utc(transition.occurred_at),
            severity=alert.severity,
            node_id=alert.node_id,
            equipment_id=alert.equipment_id,
            channel_id=alert.channel_id,
            metric=alert.metric,
            session_id=alert.session_id,
            stage_id=alert.stage_id,
            binding_id=alert.binding_id,
        )
        for alert, transition in rows
    ]


def _session_payload(row: TestSession) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "session_number": row.session_number,
        "node_id": row.node_id,
        "state": row.state,
        "title": row.title,
        "customer": row.customer,
        "test_object": row.test_object,
        "model": row.model,
        "serial_number": row.serial_number,
        "standard": row.standard,
        "method": row.method,
        "operator_id": row.operator_id,
        "responsible_engineer_id": row.responsible_engineer_id,
        "metadata": row.metadata_payload,
        "prepared_at": _utc(row.prepared_at),
        "started_at": _utc(row.started_at),
        "completed_at": _utc(row.completed_at),
        "archived_at": _utc(row.archived_at),
    }


def _configuration_payload(row: SessionConfigSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "version": row.version,
        "source": row.source,
        "payload": row.payload,
        "content_sha256": row.content_sha256,
        "created_by": row.created_by,
        "captured_at": as_utc(row.captured_at),
    }


def _binding_payloads(
    session: Session,
    session_id: str,
    *,
    selected_binding_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    statement = select(SessionChannelBinding).where(
        SessionChannelBinding.session_id == session_id
    )
    if selected_binding_ids is not None:
        statement = statement.where(
            SessionChannelBinding.id.in_(selected_binding_ids)
        )
    rows = session.scalars(
        statement.order_by(
            SessionChannelBinding.node_id,
            SessionChannelBinding.equipment_id,
            SessionChannelBinding.channel_id,
            SessionChannelBinding.metric,
            SessionChannelBinding.unit,
            SessionChannelBinding.id,
        )
    )
    return [
        {
            "id": row.id,
            "node_id": row.node_id,
            "equipment_id": row.equipment_id,
            "channel_id": row.channel_id,
            "metric": row.metric,
            "unit": row.unit,
            "metadata": row.binding_metadata,
            "activated_at": _utc(row.activated_at),
            "released_at": _utc(row.released_at),
        }
        for row in rows
    ]


def _limit_payloads(
    session: Session,
    session_id: str,
    *,
    selected_binding_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    statement = select(SessionLimit).where(SessionLimit.session_id == session_id)
    if selected_binding_ids is not None:
        statement = statement.where(
            or_(
                SessionLimit.binding_id.is_(None),
                SessionLimit.binding_id.in_(selected_binding_ids),
            )
        )
    rows = session.scalars(
        statement.order_by(SessionLimit.version, SessionLimit.metric, SessionLimit.id)
    )
    return [
        {
            "id": row.id,
            "binding_id": row.binding_id,
            "config_snapshot_id": row.config_snapshot_id,
            "supersedes_limit_id": row.supersedes_limit_id,
            "metric": row.metric,
            "unit": row.unit,
            "version": row.version,
            "lower_limit": row.lower_limit,
            "upper_limit": row.upper_limit,
            "hysteresis": row.hysteresis,
            "duration_seconds": row.duration_seconds,
            "payload": row.payload,
            "created_by": row.created_by,
            "effective_at": as_utc(row.effective_at),
        }
        for row in rows
    ]


def _stage_payloads(session: Session, session_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(SessionStage)
        .where(SessionStage.session_id == session_id)
        .order_by(SessionStage.sequence_index, SessionStage.id)
    )
    return [
        {
            "id": row.id,
            "sequence_index": row.sequence_index,
            "stage_type": row.stage_type,
            "name": row.name,
            "description": row.description,
            "planned_duration_seconds": row.planned_duration_seconds,
            "entered_at": _utc(row.entered_at),
            "exited_at": _utc(row.exited_at),
        }
        for row in rows
    ]


def _note_payloads(session: Session, session_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(SessionNote)
        .where(SessionNote.session_id == session_id)
        .order_by(SessionNote.created_at, SessionNote.id)
    )
    return [
        {
            "id": row.id,
            "stage_id": row.stage_id,
            "author_id": row.author_id,
            "body": row.body,
            "created_at": as_utc(row.created_at),
        }
        for row in rows
    ]


def _event_payloads(session: Session, session_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(SessionEvent)
        .where(SessionEvent.session_id == session_id)
        .order_by(SessionEvent.occurred_at, SessionEvent.id)
    )
    return [
        {
            "id": row.id,
            "event_type": row.event_type,
            "previous_state": row.previous_state,
            "next_state": row.next_state,
            "actor_id": row.actor_id,
            "actor_source": row.actor_source,
            "reason": row.reason,
            "payload": row.payload,
            "idempotency_key": row.idempotency_key,
            "occurred_at": as_utc(row.occurred_at),
        }
        for row in rows
    ]


def _audit_payloads(session: Session, session_id: str) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AuditLog)
        .where(AuditLog.session_id == session_id)
        .order_by(AuditLog.occurred_at, AuditLog.id)
    )
    return [
        {
            "id": row.id,
            "session_event_id": row.session_event_id,
            "actor_id": row.actor_id,
            "actor_source": row.actor_source,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "payload": row.payload,
            "occurred_at": as_utc(row.occurred_at),
        }
        for row in rows
    ]


def _utc(value: Any) -> Any:
    return as_utc(value) if value is not None else None
