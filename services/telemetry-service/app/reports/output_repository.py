from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.reports.approval import (
    ApprovalCommand,
    ApprovalSnapshot,
    ReportApprovalDecision,
    ReportApprovalState,
    approve_report,
    supersede_report,
)
from app.reports.domain import canonical_json_bytes, sha256_hex
from app.reports.models import (
    REPORT_RENDER_FORMATS,
    TestReportApprovalEvent,
    TestReportArtifact,
    TestReportRender,
    TestReportVersion,
)
from app.reports.pdf_renderer import render_pdf_protocol
from app.reports.renderer import render_xlsx_report
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository
from app.sessions.time_utils import as_utc


class ReportOutputRepositoryError(RuntimeError):
    code = "report_output_repository_error"


class ReportOutputNotFoundError(ReportOutputRepositoryError):
    code = "report_output_not_found"


class ReportOutputIdempotencyConflictError(ReportOutputRepositoryError):
    code = "report_output_idempotency_conflict"


class ReportReplacementError(ReportOutputRepositoryError):
    code = "report_replacement_invalid"


@dataclass(frozen=True, slots=True)
class StoredRender:
    render: TestReportRender
    replayed: bool


@dataclass(frozen=True, slots=True)
class StoredApproval:
    event: TestReportApprovalEvent
    snapshot: ApprovalSnapshot
    decision: ReportApprovalDecision


@dataclass(frozen=True, slots=True)
class SupersedeCommand:
    idempotency_key: str
    actor_subject: str
    reason: str
    expected_manifest_sha256: str
    replacement_report_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        _required_text(self.idempotency_key, "idempotency_key", 128)
        _required_text(self.actor_subject, "actor_subject", 255)
        _required_text(self.reason, "reason", 2000)
        _required_sha256(self.expected_manifest_sha256, "expected_manifest_sha256")
        _required_text(self.replacement_report_id, "replacement_report_id", 36)
        _aware_utc(self.occurred_at)

    @property
    def command_sha256(self) -> str:
        return sha256_hex(
            canonical_json_bytes(
                {
                    "action": "supersede",
                    "idempotency_key": self.idempotency_key,
                    "actor_subject": self.actor_subject,
                    "reason": self.reason,
                    "expected_manifest_sha256": self.expected_manifest_sha256,
                    "replacement_report_id": self.replacement_report_id,
                    "occurred_at": self.occurred_at,
                }
            )
        )


class ReportOutputRepository:
    def __init__(
        self,
        database: Database,
        *,
        security_repository: SecurityRepository | None = None,
        organization_id: str | None = None,
    ) -> None:
        self._database = database
        self._engine = database.engine
        self._security_repository = security_repository
        self._organization_id = organization_id

    def for_organization(self, organization_id: str) -> "ReportOutputRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return ReportOutputRepository(
            self._database,
            security_repository=self._security_repository,
            organization_id=normalized,
        )

    def render(
        self,
        report_id: str,
        *,
        format_name: str,
        idempotency_key: str,
        rendered_by: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        expected_manifest_sha256: str | None = None,
        reason: str | None = None,
    ) -> StoredRender:
        organization_id = self._scope()
        normalized_report_id = _required_text(report_id, "report_id", 36)
        normalized_format = _render_format(format_name)
        key = _required_text(idempotency_key, "idempotency_key", 128)
        actor = _required_text(rendered_by, "rendered_by", 255)
        expected = _optional_sha256(
            expected_manifest_sha256,
            "expected_manifest_sha256",
        )

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                replay = session.scalar(
                    select(TestReportRender).where(
                        TestReportRender.organization_id == organization_id,
                        TestReportRender.idempotency_key == key,
                    )
                )
                if replay is not None:
                    if (
                        replay.report_id != normalized_report_id
                        or replay.format != normalized_format
                        or replay.rendered_by != actor
                        or (
                            expected is not None
                            and replay.manifest_sha256 != expected
                        )
                    ):
                        raise ReportOutputIdempotencyConflictError(
                            "render idempotency key is bound to a different command"
                        )
                    session.expunge(replay)
                    return StoredRender(replay, replayed=True)

                report = self._report_for_update(session, normalized_report_id)
                if expected is not None and report.manifest_sha256 != expected:
                    raise ReportOutputRepositoryError(
                        "report manifest does not match render precondition"
                    )
                artifacts = {
                    artifact.name: artifact.content
                    for artifact in self._artifacts(session, report.id)
                }
                rendered = (
                    render_xlsx_report(artifacts)
                    if normalized_format == "xlsx"
                    else render_pdf_protocol(artifacts)
                )
                rendered_at = datetime.now(UTC)
                row = TestReportRender(
                    id=str(uuid4()),
                    report_id=report.id,
                    organization_id=organization_id,
                    format=normalized_format,
                    artifact_name=rendered.descriptor.name,
                    media_type=rendered.descriptor.media_type,
                    renderer_version=rendered.renderer_version,
                    manifest_sha256=report.manifest_sha256,
                    sha256=rendered.descriptor.sha256,
                    size_bytes=rendered.descriptor.size_bytes,
                    content=rendered.content,
                    idempotency_key=key,
                    rendered_by=actor,
                    rendered_at=rendered_at,
                    created_at=rendered_at,
                )
                session.add(row)
                session.flush([row])
                self._audit(
                    session,
                    report=report,
                    identity_id=actor_identity_id,
                    actor_subject=actor,
                    actor_roles=actor_roles,
                    action="report.rendered",
                    entity_type="test_report_render",
                    entity_id=row.id,
                    reason=reason,
                    after_snapshot={
                        "format": row.format,
                        "artifact_name": row.artifact_name,
                        "renderer_version": row.renderer_version,
                        "manifest_sha256": row.manifest_sha256,
                        "sha256": row.sha256,
                        "size_bytes": row.size_bytes,
                    },
                )
            session.expunge(row)
            return StoredRender(row, replayed=False)

    def get_render(self, render_id: str) -> TestReportRender:
        normalized = _required_text(render_id, "render_id", 36)
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.scalar(
                select(TestReportRender).where(
                    TestReportRender.id == normalized,
                    TestReportRender.organization_id == self._scope(),
                )
            )
            if row is None:
                raise ReportOutputNotFoundError(
                    f"render {normalized!r} was not found"
                )
            session.expunge(row)
            return row

    def approval_snapshot(self, report_id: str) -> ApprovalSnapshot:
        normalized = _required_text(report_id, "report_id", 36)
        with Session(self._engine) as session:
            report = self._report(session, normalized)
            return self._snapshot(session, report)

    def approve(
        self,
        report_id: str,
        command: ApprovalCommand,
        *,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
    ) -> StoredApproval:
        normalized = _required_text(report_id, "report_id", 36)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                report = self._report_for_update(session, normalized)
                replay = self._approval_event_by_key(
                    session,
                    command.idempotency_key,
                )
                if replay is not None:
                    if (
                        replay.report_id != report.id
                        or replay.event_type != "approved"
                        or replay.command_sha256 != command.command_sha256
                    ):
                        raise ReportOutputIdempotencyConflictError(
                            "approval idempotency key is bound to a different command"
                        )
                    snapshot = self._snapshot(session, report)
                    session.expunge(replay)
                    return StoredApproval(
                        replay,
                        snapshot,
                        ReportApprovalDecision.REPLAY,
                    )

                snapshot = self._snapshot(session, report)
                result = approve_report(snapshot, command)
                event = TestReportApprovalEvent(
                    id=str(uuid4()),
                    report_id=report.id,
                    organization_id=report.organization_id,
                    event_type="approved",
                    manifest_sha256=report.manifest_sha256,
                    command_sha256=command.command_sha256,
                    idempotency_key=command.idempotency_key,
                    actor_identity_id=actor_identity_id,
                    actor_subject=command.actor_subject,
                    reason=command.reason,
                    occurred_at=command.occurred_at.astimezone(UTC),
                    superseded_by_report_id=None,
                    created_at=command.occurred_at.astimezone(UTC),
                )
                session.add(event)
                session.flush([event])
                self._audit(
                    session,
                    report=report,
                    identity_id=actor_identity_id,
                    actor_subject=command.actor_subject,
                    actor_roles=actor_roles,
                    action="report.approved",
                    entity_type="test_report_approval_event",
                    entity_id=event.id,
                    reason=command.reason,
                    after_snapshot={
                        "state": result.snapshot.state.value,
                        "manifest_sha256": report.manifest_sha256,
                        "command_sha256": command.command_sha256,
                        "approved_at": event.occurred_at,
                    },
                )
            session.expunge(event)
            return StoredApproval(event, result.snapshot, result.decision)

    def supersede(
        self,
        report_id: str,
        command: SupersedeCommand,
        *,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
    ) -> StoredApproval:
        normalized = _required_text(report_id, "report_id", 36)
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                report = self._report_for_update(session, normalized)
                replay = self._approval_event_by_key(
                    session,
                    command.idempotency_key,
                )
                if replay is not None:
                    if (
                        replay.report_id != report.id
                        or replay.event_type != "superseded"
                        or replay.command_sha256 != command.command_sha256
                    ):
                        raise ReportOutputIdempotencyConflictError(
                            "supersede idempotency key is bound to a different command"
                        )
                    snapshot = self._snapshot(session, report)
                    session.expunge(replay)
                    return StoredApproval(
                        replay,
                        snapshot,
                        ReportApprovalDecision.REPLAY,
                    )

                if report.manifest_sha256 != command.expected_manifest_sha256:
                    raise ReportOutputRepositoryError(
                        "report manifest does not match supersede precondition"
                    )
                replacement = self._report(session, command.replacement_report_id)
                if (
                    replacement.session_id != report.session_id
                    or replacement.version <= report.version
                ):
                    raise ReportReplacementError(
                        "replacement must be a later report version for the same session"
                    )
                snapshot = self._snapshot(session, report)
                result = supersede_report(
                    snapshot,
                    replacement_report_id=replacement.id,
                    occurred_at=command.occurred_at,
                )
                event = TestReportApprovalEvent(
                    id=str(uuid4()),
                    report_id=report.id,
                    organization_id=report.organization_id,
                    event_type="superseded",
                    manifest_sha256=report.manifest_sha256,
                    command_sha256=command.command_sha256,
                    idempotency_key=command.idempotency_key,
                    actor_identity_id=actor_identity_id,
                    actor_subject=command.actor_subject,
                    reason=command.reason,
                    occurred_at=command.occurred_at.astimezone(UTC),
                    superseded_by_report_id=replacement.id,
                    created_at=command.occurred_at.astimezone(UTC),
                )
                session.add(event)
                session.flush([event])
                self._audit(
                    session,
                    report=report,
                    identity_id=actor_identity_id,
                    actor_subject=command.actor_subject,
                    actor_roles=actor_roles,
                    action="report.superseded",
                    entity_type="test_report_approval_event",
                    entity_id=event.id,
                    reason=command.reason,
                    after_snapshot={
                        "state": result.snapshot.state.value,
                        "manifest_sha256": report.manifest_sha256,
                        "command_sha256": command.command_sha256,
                        "superseded_by_report_id": replacement.id,
                        "superseded_at": event.occurred_at,
                    },
                )
            session.expunge(event)
            return StoredApproval(event, result.snapshot, result.decision)

    def _scope(self) -> str:
        if self._organization_id is None:
            raise ReportOutputRepositoryError("organization scope is required")
        return self._organization_id

    def _report(
        self,
        session: Session,
        report_id: str,
    ) -> TestReportVersion:
        report = session.scalar(
            select(TestReportVersion).where(
                TestReportVersion.id == report_id,
                TestReportVersion.organization_id == self._scope(),
            )
        )
        if report is None:
            raise ReportOutputNotFoundError(f"report {report_id!r} was not found")
        return report

    def _report_for_update(
        self,
        session: Session,
        report_id: str,
    ) -> TestReportVersion:
        report = session.scalar(
            select(TestReportVersion)
            .where(
                TestReportVersion.id == report_id,
                TestReportVersion.organization_id == self._scope(),
            )
            .with_for_update()
        )
        if report is None:
            raise ReportOutputNotFoundError(f"report {report_id!r} was not found")
        return report

    @staticmethod
    def _artifacts(
        session: Session,
        report_id: str,
    ) -> list[TestReportArtifact]:
        return list(
            session.scalars(
                select(TestReportArtifact)
                .where(TestReportArtifact.report_id == report_id)
                .order_by(TestReportArtifact.name)
            )
        )

    def _approval_event_by_key(
        self,
        session: Session,
        key: str,
    ) -> TestReportApprovalEvent | None:
        return session.scalar(
            select(TestReportApprovalEvent).where(
                TestReportApprovalEvent.organization_id == self._scope(),
                TestReportApprovalEvent.idempotency_key == key,
            )
        )

    @staticmethod
    def _snapshot(
        session: Session,
        report: TestReportVersion,
    ) -> ApprovalSnapshot:
        events = list(
            session.scalars(
                select(TestReportApprovalEvent)
                .where(TestReportApprovalEvent.report_id == report.id)
                .order_by(
                    TestReportApprovalEvent.occurred_at,
                    TestReportApprovalEvent.id,
                )
            )
        )
        snapshot = ApprovalSnapshot(manifest_sha256=report.manifest_sha256)
        for event in events:
            if event.manifest_sha256 != report.manifest_sha256:
                raise ReportOutputRepositoryError(
                    "approval event manifest does not match immutable report"
                )
            if event.event_type == "approved":
                if snapshot.state is not ReportApprovalState.GENERATED:
                    raise ReportOutputRepositoryError(
                        "approval event stream contains an invalid transition"
                    )
                snapshot = ApprovalSnapshot(
                    state=ReportApprovalState.APPROVED,
                    manifest_sha256=report.manifest_sha256,
                    approved_by=event.actor_subject,
                    approved_at=as_utc(event.occurred_at),
                    approval_reason=event.reason,
                    approval_idempotency_key=event.idempotency_key,
                    approval_command_sha256=event.command_sha256,
                )
                continue
            if event.event_type == "superseded":
                if snapshot.state is not ReportApprovalState.APPROVED:
                    raise ReportOutputRepositoryError(
                        "supersede event has no preceding approval"
                    )
                snapshot = supersede_report(
                    snapshot,
                    replacement_report_id=event.superseded_by_report_id or "",
                    occurred_at=as_utc(event.occurred_at),
                ).snapshot
                continue
            raise ReportOutputRepositoryError(
                f"unsupported approval event type: {event.event_type}"
            )
        return snapshot

    def _audit(
        self,
        session: Session,
        *,
        report: TestReportVersion,
        identity_id: str | None,
        actor_subject: str,
        actor_roles: frozenset[Role],
        action: str,
        entity_type: str,
        entity_id: str,
        reason: str | None,
        after_snapshot: dict[str, Any],
    ) -> None:
        if self._security_repository is None:
            return
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=report.organization_id,
                actor_identity_id=identity_id,
                actor_subject=actor_subject,
                actor_roles=actor_roles,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                after_snapshot={
                    "report_id": report.id,
                    "session_id": report.session_id,
                    **after_snapshot,
                },
                reason=reason,
            ),
            session=session,
        )


def _render_format(value: str) -> str:
    normalized = _required_text(value, "format_name", 16).lower()
    if normalized not in REPORT_RENDER_FORMATS:
        raise ValueError(
            f"format_name must be one of: {', '.join(REPORT_RENDER_FORMATS)}"
        )
    return normalized


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _required_sha256(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    try:
        int(normalized, 16)
    except ValueError as error:
        raise ValueError(f"{field} must be a SHA-256 hex digest") from error
    return normalized


def _optional_sha256(value: str | None, field: str) -> str | None:
    return None if value is None else _required_sha256(value, field)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)
