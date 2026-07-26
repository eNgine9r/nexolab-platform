from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance, AlertTransition
from app.db import Database, TelemetrySample
from app.reports.domain import (
    REPORT_GENERATOR_VERSION,
    AlertTransitionEvidenceRow,
    ArtifactDescriptor,
    TelemetryEvidenceRow,
    alert_transitions_csv_bytes,
    canonical_json_bytes,
    report_manifest_bytes,
    sha256_hex,
    telemetry_csv_bytes,
)
from app.reports.models import TestReportArtifact, TestReportVersion
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


class ReportGenerationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ReportGenerationResult:
    report: TestReportVersion
    artifacts: tuple[TestReportArtifact, ...]
    replayed: bool


class ReportService:
    def __init__(
        self,
        database: Database,
        *,
        clock: Callable[[], datetime] | None = None,
        generator_version: str = REPORT_GENERATOR_VERSION,
    ) -> None:
        self._engine = database.engine
        self._clock = clock or (lambda: datetime.now(UTC))
        self._generator_version = generator_version.strip()
        if not self._generator_version:
            raise ValueError("generator_version is required")

    def generate(
        self,
        *,
        organization_id: str,
        session_id: str,
        idempotency_key: str,
        generated_by: str,
    ) -> ReportGenerationResult:
        organization_id = _required(organization_id, "organization_id")
        session_id = _required(session_id, "session_id")
        idempotency_key = _required(idempotency_key, "idempotency_key")
        generated_by = _required(generated_by, "generated_by")
        generated_at = _aware_utc(self._clock())

        with Session(self._engine, expire_on_commit=False) as database_session:
            with database_session.begin():
                existing = database_session.scalar(
                    select(TestReportVersion).where(
                        TestReportVersion.organization_id == organization_id,
                        TestReportVersion.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    if existing.session_id != session_id:
                        raise ReportGenerationError(
                            "report_idempotency_conflict",
                            "idempotency key belongs to a different session",
                        )
                    artifacts = self._artifacts(database_session, existing.id)
                    return ReportGenerationResult(
                        report=existing,
                        artifacts=tuple(artifacts),
                        replayed=True,
                    )

                test_session = database_session.scalar(
                    select(TestSession)
                    .where(
                        TestSession.id == session_id,
                        TestSession.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if test_session is None:
                    raise ReportGenerationError(
                        "report_session_not_found",
                        f"session {session_id!r} was not found",
                    )
                if test_session.state not in {"completed", "archived"}:
                    raise ReportGenerationError(
                        "report_session_not_terminal",
                        "reports may be generated only for completed or archived sessions",
                    )
                if test_session.started_at is None or test_session.completed_at is None:
                    raise ReportGenerationError(
                        "report_source_incomplete",
                        "reportable session has no committed start/completion boundary",
                    )
                if test_session.active_config_snapshot_id is None:
                    raise ReportGenerationError(
                        "report_source_incomplete",
                        "reportable session has no active configuration snapshot",
                    )

                config_snapshot = database_session.scalar(
                    select(SessionConfigSnapshot).where(
                        SessionConfigSnapshot.id
                        == test_session.active_config_snapshot_id,
                        SessionConfigSnapshot.session_id == test_session.id,
                    )
                )
                if config_snapshot is None:
                    raise ReportGenerationError(
                        "report_source_incomplete",
                        "active configuration snapshot was not found",
                    )

                version = (
                    database_session.scalar(
                        select(func.max(TestReportVersion.version)).where(
                            TestReportVersion.session_id == test_session.id
                        )
                    )
                    or 0
                ) + 1
                report_id = str(uuid4())

                telemetry_rows = self._telemetry_rows(database_session, test_session.id)
                alert_rows = self._alert_rows(
                    database_session,
                    organization_id=organization_id,
                    session_id=test_session.id,
                )
                source = self._source_snapshot(
                    database_session,
                    test_session=test_session,
                    config_snapshot=config_snapshot,
                    telemetry_count=len(telemetry_rows),
                    alert_transition_count=len(alert_rows),
                )
                source_bytes = canonical_json_bytes(source)
                normalized_source = json.loads(source_bytes)
                telemetry_bytes = telemetry_csv_bytes(telemetry_rows)
                alerts_bytes = alert_transitions_csv_bytes(alert_rows)

                descriptors = [
                    ArtifactDescriptor.from_bytes(
                        name="alerts.csv",
                        media_type="text/csv",
                        content=alerts_bytes,
                        row_count=len(alert_rows),
                    ),
                    ArtifactDescriptor.from_bytes(
                        name="source.json",
                        media_type="application/json",
                        content=source_bytes,
                    ),
                    ArtifactDescriptor.from_bytes(
                        name="telemetry.csv",
                        media_type="text/csv",
                        content=telemetry_bytes,
                        row_count=len(telemetry_rows),
                    ),
                ]
                source_sha256 = sha256_hex(source_bytes)
                manifest_bytes = report_manifest_bytes(
                    report_id=report_id,
                    organization_id=organization_id,
                    session_id=test_session.id,
                    report_version=version,
                    source_sha256=source_sha256,
                    generated_at=generated_at,
                    generated_by=generated_by,
                    generator_version=self._generator_version,
                    artifacts=descriptors,
                )
                manifest_descriptor = ArtifactDescriptor.from_bytes(
                    name="manifest.json",
                    media_type="application/json",
                    content=manifest_bytes,
                )

                report = TestReportVersion(
                    id=report_id,
                    organization_id=organization_id,
                    session_id=test_session.id,
                    config_snapshot_id=config_snapshot.id,
                    version=version,
                    idempotency_key=idempotency_key,
                    session_state=test_session.state,
                    source_started_at=_aware_utc(test_session.started_at),
                    source_ended_at=_aware_utc(test_session.completed_at),
                    source_snapshot=normalized_source,
                    source_sha256=source_sha256,
                    manifest_sha256=manifest_descriptor.sha256,
                    generator_version=self._generator_version,
                    generated_by=generated_by,
                    generated_at=generated_at,
                )
                database_session.add(report)
                database_session.flush([report])

                artifact_content = {
                    "alerts.csv": alerts_bytes,
                    "source.json": source_bytes,
                    "telemetry.csv": telemetry_bytes,
                    "manifest.json": manifest_bytes,
                }
                persisted_artifacts: list[TestReportArtifact] = []
                for descriptor in (*descriptors, manifest_descriptor):
                    artifact = TestReportArtifact(
                        id=str(uuid4()),
                        report_id=report.id,
                        name=descriptor.name,
                        media_type=descriptor.media_type,
                        sha256=descriptor.sha256,
                        size_bytes=descriptor.size_bytes,
                        row_count=descriptor.row_count,
                        content=artifact_content[descriptor.name],
                    )
                    database_session.add(artifact)
                    persisted_artifacts.append(artifact)
                database_session.flush(persisted_artifacts)

            return ReportGenerationResult(
                report=report,
                artifacts=tuple(sorted(persisted_artifacts, key=lambda item: item.name)),
                replayed=False,
            )

    def list_reports(
        self,
        *,
        organization_id: str,
        session_id: str | None = None,
    ) -> list[TestReportVersion]:
        statement = select(TestReportVersion).where(
            TestReportVersion.organization_id == organization_id
        )
        if session_id is not None:
            statement = statement.where(TestReportVersion.session_id == session_id)
        statement = statement.order_by(
            TestReportVersion.generated_at.desc(),
            TestReportVersion.id.desc(),
        )
        with Session(self._engine) as database_session:
            return list(database_session.scalars(statement))

    def get_report(
        self,
        *,
        organization_id: str,
        report_id: str,
    ) -> TestReportVersion | None:
        with Session(self._engine) as database_session:
            return database_session.scalar(
                select(TestReportVersion).where(
                    TestReportVersion.id == report_id,
                    TestReportVersion.organization_id == organization_id,
                )
            )

    def get_artifact(
        self,
        *,
        organization_id: str,
        report_id: str,
        artifact_name: str,
    ) -> TestReportArtifact | None:
        with Session(self._engine) as database_session:
            return database_session.scalar(
                select(TestReportArtifact)
                .join(
                    TestReportVersion,
                    TestReportVersion.id == TestReportArtifact.report_id,
                )
                .where(
                    TestReportVersion.id == report_id,
                    TestReportVersion.organization_id == organization_id,
                    TestReportArtifact.name == artifact_name,
                )
            )

    @staticmethod
    def _artifacts(
        database_session: Session,
        report_id: str,
    ) -> list[TestReportArtifact]:
        return list(
            database_session.scalars(
                select(TestReportArtifact)
                .where(TestReportArtifact.report_id == report_id)
                .order_by(TestReportArtifact.name)
            )
        )

    @staticmethod
    def _telemetry_rows(
        database_session: Session,
        session_id: str,
    ) -> list[TelemetryEvidenceRow]:
        sample = TelemetrySample
        context = TelemetrySessionContext
        statement = (
            select(
                sample.event_id,
                sample.captured_at,
                sample.node_id,
                sample.equipment_id,
                sample.channel_id,
                sample.metric,
                sample.value,
                sample.unit,
                sample.quality,
                sample.alarm,
                sample.source,
                context.session_id,
                context.stage_id,
                context.binding_id,
                context.config_snapshot_id,
            )
            .join(context, sample.event_id == context.telemetry_event_id)
            .where(context.session_id == session_id)
            .order_by(sample.captured_at, sample.event_id)
        )
        return [
            TelemetryEvidenceRow(**dict(row))
            for row in database_session.execute(statement).mappings()
        ]

    @staticmethod
    def _alert_rows(
        database_session: Session,
        *,
        organization_id: str,
        session_id: str,
    ) -> list[AlertTransitionEvidenceRow]:
        statement = (
            select(AlertInstance, AlertTransition)
            .join(AlertTransition, AlertTransition.alert_id == AlertInstance.id)
            .where(
                AlertInstance.organization_id == organization_id,
                AlertInstance.session_id == session_id,
            )
            .order_by(
                AlertTransition.occurred_at,
                AlertInstance.id,
                AlertTransition.id,
            )
        )
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
                occurred_at=transition.occurred_at,
                severity=alert.severity,
                node_id=alert.node_id,
                equipment_id=alert.equipment_id,
                channel_id=alert.channel_id,
                metric=alert.metric,
                session_id=alert.session_id,
                stage_id=alert.stage_id,
                binding_id=alert.binding_id,
            )
            for alert, transition in database_session.execute(statement)
        ]

    @staticmethod
    def _source_snapshot(
        database_session: Session,
        *,
        test_session: TestSession,
        config_snapshot: SessionConfigSnapshot,
        telemetry_count: int,
        alert_transition_count: int,
    ) -> dict[str, Any]:
        bindings = list(
            database_session.scalars(
                select(SessionChannelBinding)
                .where(SessionChannelBinding.session_id == test_session.id)
                .order_by(
                    SessionChannelBinding.node_id,
                    SessionChannelBinding.equipment_id,
                    SessionChannelBinding.channel_id,
                    SessionChannelBinding.metric,
                    SessionChannelBinding.id,
                )
            )
        )
        limits = list(
            database_session.scalars(
                select(SessionLimit)
                .where(SessionLimit.session_id == test_session.id)
                .order_by(
                    SessionLimit.version,
                    SessionLimit.metric,
                    SessionLimit.binding_id,
                    SessionLimit.id,
                )
            )
        )
        stages = list(
            database_session.scalars(
                select(SessionStage)
                .where(SessionStage.session_id == test_session.id)
                .order_by(SessionStage.sequence_index, SessionStage.id)
            )
        )
        notes = list(
            database_session.scalars(
                select(SessionNote)
                .where(SessionNote.session_id == test_session.id)
                .order_by(SessionNote.created_at, SessionNote.id)
            )
        )
        events = list(
            database_session.scalars(
                select(SessionEvent)
                .where(SessionEvent.session_id == test_session.id)
                .order_by(SessionEvent.occurred_at, SessionEvent.id)
            )
        )
        audit_rows = list(
            database_session.scalars(
                select(AuditLog)
                .where(AuditLog.session_id == test_session.id)
                .order_by(AuditLog.occurred_at, AuditLog.id)
            )
        )
        alerts = list(
            database_session.scalars(
                select(AlertInstance)
                .where(AlertInstance.session_id == test_session.id)
                .order_by(AlertInstance.triggered_at, AlertInstance.id)
            )
        )
        transitions = list(
            database_session.scalars(
                select(AlertTransition)
                .join(AlertInstance, AlertInstance.id == AlertTransition.alert_id)
                .where(AlertInstance.session_id == test_session.id)
                .order_by(AlertTransition.occurred_at, AlertTransition.id)
            )
        )

        return {
            "schema": "nexolab.report-source.v1",
            "source_window": {
                "from": test_session.started_at,
                "to": test_session.completed_at,
                "end_exclusive": True,
            },
            "session": {
                "id": test_session.id,
                "organization_id": test_session.organization_id,
                "session_number": test_session.session_number,
                "node_id": test_session.node_id,
                "state": test_session.state,
                "title": test_session.title,
                "customer": test_session.customer,
                "test_object": test_session.test_object,
                "model": test_session.model,
                "serial_number": test_session.serial_number,
                "standard": test_session.standard,
                "method": test_session.method,
                "operator_id": test_session.operator_id,
                "responsible_engineer_id": test_session.responsible_engineer_id,
                "metadata": test_session.metadata_payload,
                "prepared_at": test_session.prepared_at,
                "started_at": test_session.started_at,
                "completed_at": test_session.completed_at,
                "archived_at": test_session.archived_at,
                "active_config_snapshot_id": test_session.active_config_snapshot_id,
                "active_limit_version": test_session.active_limit_version,
            },
            "configuration_snapshot": {
                "id": config_snapshot.id,
                "version": config_snapshot.version,
                "source": config_snapshot.source,
                "payload": config_snapshot.payload,
                "content_sha256": config_snapshot.content_sha256,
                "created_by": config_snapshot.created_by,
                "captured_at": config_snapshot.captured_at,
            },
            "bindings": [
                {
                    "id": row.id,
                    "node_id": row.node_id,
                    "equipment_id": row.equipment_id,
                    "channel_id": row.channel_id,
                    "metric": row.metric,
                    "unit": row.unit,
                    "metadata": row.binding_metadata,
                    "activated_at": row.activated_at,
                    "released_at": row.released_at,
                }
                for row in bindings
            ],
            "limits": [
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
                    "effective_at": row.effective_at,
                }
                for row in limits
            ],
            "stages": [
                {
                    "id": row.id,
                    "sequence_index": row.sequence_index,
                    "stage_type": row.stage_type,
                    "name": row.name,
                    "description": row.description,
                    "planned_duration_seconds": row.planned_duration_seconds,
                    "entered_at": row.entered_at,
                    "exited_at": row.exited_at,
                }
                for row in stages
            ],
            "notes": [
                {
                    "id": row.id,
                    "stage_id": row.stage_id,
                    "author_id": row.author_id,
                    "body": row.body,
                    "created_at": row.created_at,
                }
                for row in notes
            ],
            "events": [
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
                    "occurred_at": row.occurred_at,
                }
                for row in events
            ],
            "audit_references": [
                {
                    "id": row.id,
                    "session_event_id": row.session_event_id,
                    "actor_id": row.actor_id,
                    "actor_source": row.actor_source,
                    "action": row.action,
                    "entity_type": row.entity_type,
                    "entity_id": row.entity_id,
                    "occurred_at": row.occurred_at,
                }
                for row in audit_rows
            ],
            "alerts": [
                {
                    "id": row.id,
                    "rule_id": row.rule_id,
                    "rule_version_id": row.rule_version_id,
                    "state": row.state,
                    "severity": row.severity,
                    "node_id": row.node_id,
                    "equipment_id": row.equipment_id,
                    "channel_id": row.channel_id,
                    "metric": row.metric,
                    "trigger_value": row.trigger_value,
                    "trigger_threshold": row.trigger_threshold,
                    "clear_threshold": row.clear_threshold,
                    "maximum_deviation": row.maximum_deviation,
                    "first_event_id": row.first_event_id,
                    "last_event_id": row.last_event_id,
                    "stage_id": row.stage_id,
                    "binding_id": row.binding_id,
                    "context": row.context,
                    "triggered_at": row.triggered_at,
                    "acknowledged_at": row.acknowledged_at,
                    "resolved_at": row.resolved_at,
                    "closed_at": row.closed_at,
                }
                for row in alerts
            ],
            "alert_transitions": [
                {
                    "id": row.id,
                    "alert_id": row.alert_id,
                    "event_type": row.event_type,
                    "previous_state": row.previous_state,
                    "next_state": row.next_state,
                    "actor_id": row.actor_id,
                    "actor_source": row.actor_source,
                    "reason": row.reason,
                    "idempotency_key": row.idempotency_key,
                    "payload": row.payload,
                    "occurred_at": row.occurred_at,
                }
                for row in transitions
            ],
            "counts": {
                "bindings": len(bindings),
                "limits": len(limits),
                "stages": len(stages),
                "notes": len(notes),
                "events": len(events),
                "audit_references": len(audit_rows),
                "telemetry": telemetry_count,
                "alerts": len(alerts),
                "alert_transitions": alert_transition_count,
            },
        }


def _required(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} is required")
    return normalized


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime values must be timezone-aware")
    return value.astimezone(UTC)
