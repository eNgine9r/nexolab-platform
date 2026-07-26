from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database
from app.reports.domain import (
    REPORT_GENERATOR_VERSION,
    ArtifactDescriptor,
    alert_transitions_csv_bytes,
    canonical_json_bytes,
    report_manifest_bytes,
    sha256_hex,
    telemetry_csv_bytes,
)
from app.reports.models import TestReportArtifact, TestReportVersion
from app.reports.source import REPORT_SOURCE_SCHEMA, assemble_report_source
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository
from app.sessions.models import SessionConfigSnapshot, TestSession
from app.sessions.time_utils import as_utc


class ReportRepositoryError(RuntimeError):
    code = "report_repository_error"


class ReportNotFoundError(ReportRepositoryError):
    code = "report_not_found"


class ReportSessionNotFoundError(ReportRepositoryError):
    code = "report_session_not_found"


class ReportSessionStateError(ReportRepositoryError):
    code = "report_session_not_reportable"


class ReportSourceChangedError(ReportRepositoryError):
    code = "report_source_changed"


class ReportIdempotencyConflictError(ReportRepositoryError):
    code = "report_idempotency_conflict"


@dataclass(frozen=True, slots=True)
class ReportPage:
    items: list[TestReportVersion]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class ReportRecord:
    report: TestReportVersion
    artifacts: list[TestReportArtifact]
    replayed: bool = False


class ReportRepository:
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

    def for_organization(self, organization_id: str) -> "ReportRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return ReportRepository(
            self._database,
            security_repository=self._security_repository,
            organization_id=normalized,
        )

    def generate(
        self,
        session_id: str,
        *,
        idempotency_key: str,
        generated_by: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        expected_source_sha256: str | None = None,
        reason: str | None = None,
    ) -> ReportRecord:
        organization_id = self._scope()
        key = _required_text(idempotency_key, "idempotency_key", 128)
        actor = _required_text(generated_by, "generated_by", 255)
        expected = _optional_sha256(expected_source_sha256)

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                test_session = session.scalar(
                    select(TestSession)
                    .where(
                        TestSession.id == session_id,
                        TestSession.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if test_session is None:
                    raise ReportSessionNotFoundError(
                        f"session {session_id!r} was not found"
                    )

                replay = self._find_by_idempotency(session, key)
                if replay is not None:
                    if replay.session_id != session_id:
                        raise ReportIdempotencyConflictError(
                            "idempotency key is already bound to another session"
                        )
                    if expected is not None and replay.source_sha256 != expected:
                        raise ReportSourceChangedError(
                            "existing report source digest does not match expectation"
                        )
                    return self._detach(
                        session,
                        ReportRecord(
                            replay,
                            self._artifacts(session, replay.id),
                            replayed=True,
                        ),
                    )

                self._validate_session(test_session)
                config_snapshot = self._config_snapshot(session, test_session)
                source = assemble_report_source(
                    session,
                    test_session,
                    config_snapshot,
                )
                telemetry_content = telemetry_csv_bytes(source.telemetry)
                alerts_content = alert_transitions_csv_bytes(
                    source.alert_transitions
                )
                telemetry_descriptor = ArtifactDescriptor.from_bytes(
                    name="telemetry.csv",
                    media_type="text/csv; charset=utf-8",
                    content=telemetry_content,
                    row_count=len(source.telemetry),
                )
                alerts_descriptor = ArtifactDescriptor.from_bytes(
                    name="alert-transitions.csv",
                    media_type="text/csv; charset=utf-8",
                    content=alerts_content,
                    row_count=len(source.alert_transitions),
                )
                source_payload = {
                    "schema": REPORT_SOURCE_SCHEMA,
                    "organization_id": organization_id,
                    "session_id": test_session.id,
                    "source_started_at": as_utc(test_session.started_at),
                    "source_ended_at": as_utc(test_session.completed_at),
                    "metadata": source.metadata,
                    "evidence": {
                        "telemetry": _descriptor(telemetry_descriptor),
                        "alert_transitions": _descriptor(alerts_descriptor),
                    },
                }
                source_content = canonical_json_bytes(source_payload)
                source_sha256 = sha256_hex(source_content)
                if expected is not None and source_sha256 != expected:
                    raise ReportSourceChangedError(
                        "current report source digest does not match expectation"
                    )

                version = self._next_version(session, test_session.id)
                generated_at = datetime.now(UTC)
                report_id = str(uuid4())
                source_descriptor = ArtifactDescriptor.from_bytes(
                    name="source-snapshot.json",
                    media_type="application/json",
                    content=source_content,
                )
                manifest_content = report_manifest_bytes(
                    report_id=report_id,
                    organization_id=organization_id,
                    session_id=test_session.id,
                    report_version=version,
                    source_sha256=source_sha256,
                    generated_at=generated_at,
                    generated_by=actor,
                    artifacts=(
                        source_descriptor,
                        telemetry_descriptor,
                        alerts_descriptor,
                    ),
                )
                report = TestReportVersion(
                    id=report_id,
                    organization_id=organization_id,
                    session_id=test_session.id,
                    config_snapshot_id=config_snapshot.id,
                    version=version,
                    idempotency_key=key,
                    session_state=test_session.state,
                    source_started_at=as_utc(test_session.started_at),
                    source_ended_at=as_utc(test_session.completed_at),
                    source_snapshot=json.loads(source_content),
                    source_sha256=source_sha256,
                    manifest_sha256=sha256_hex(manifest_content),
                    generator_version=REPORT_GENERATOR_VERSION,
                    generated_by=actor,
                    generated_at=generated_at,
                    created_at=generated_at,
                )
                artifacts = _artifact_rows(
                    report_id,
                    generated_at,
                    (
                        (source_descriptor, source_content),
                        (telemetry_descriptor, telemetry_content),
                        (alerts_descriptor, alerts_content),
                        (
                            ArtifactDescriptor.from_bytes(
                                name="manifest.json",
                                media_type="application/json",
                                content=manifest_content,
                            ),
                            manifest_content,
                        ),
                    ),
                )
                session.add(report)
                # Artifacts reference report_id without an ORM relationship, so
                # persist the immutable parent before inserting its exact bytes.
                session.flush([report])
                session.add_all(artifacts)
                session.flush(artifacts)
                self._audit_generation(
                    session,
                    report,
                    identity_id=actor_identity_id,
                    actor_subject=actor,
                    actor_roles=actor_roles,
                    reason=reason,
                )

            return self._detach(
                session,
                ReportRecord(report, artifacts, replayed=False),
            )

    def list_reports(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ReportPage:
        filters = [TestReportVersion.organization_id == self._scope()]
        if session_id is not None:
            filters.append(TestReportVersion.session_id == session_id)
        statement = (
            select(TestReportVersion)
            .where(*filters)
            .order_by(
                TestReportVersion.generated_at.desc(),
                TestReportVersion.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        count_statement = (
            select(func.count())
            .select_from(TestReportVersion)
            .where(*filters)
        )
        with Session(self._engine, expire_on_commit=False) as session:
            items = list(session.scalars(statement))
            count = int(session.scalar(count_statement) or 0)
            for item in items:
                session.expunge(item)
            return ReportPage(items, count, limit, offset)

    def get_report(self, report_id: str) -> ReportRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            report = session.scalar(
                select(TestReportVersion).where(
                    TestReportVersion.id == report_id,
                    TestReportVersion.organization_id == self._scope(),
                )
            )
            if report is None:
                raise ReportNotFoundError(f"report {report_id!r} was not found")
            return self._detach(
                session,
                ReportRecord(report, self._artifacts(session, report.id)),
            )

    def get_artifact(
        self,
        report_id: str,
        artifact_name: str,
    ) -> TestReportArtifact:
        name = _required_text(artifact_name, "artifact_name", 255)
        with Session(self._engine, expire_on_commit=False) as session:
            artifact = session.scalar(
                select(TestReportArtifact)
                .join(
                    TestReportVersion,
                    TestReportVersion.id == TestReportArtifact.report_id,
                )
                .where(
                    TestReportArtifact.report_id == report_id,
                    TestReportArtifact.name == name,
                    TestReportVersion.organization_id == self._scope(),
                )
            )
            if artifact is None:
                raise ReportNotFoundError(
                    f"artifact {artifact_name!r} was not found"
                )
            session.expunge(artifact)
            return artifact

    def audit_artifact_access(
        self,
        artifact: TestReportArtifact,
        *,
        actor_identity_id: str | None,
        actor_subject: str,
        actor_roles: frozenset[Role],
    ) -> None:
        if self._security_repository is None:
            return
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=self._scope(),
                actor_identity_id=actor_identity_id,
                actor_subject=_required_text(
                    actor_subject,
                    "actor_subject",
                    255,
                ),
                actor_roles=actor_roles,
                action="report.artifact.downloaded",
                entity_type="test_report_artifact",
                entity_id=artifact.id,
                after_snapshot={
                    "report_id": artifact.report_id,
                    "name": artifact.name,
                    "sha256": artifact.sha256,
                    "size_bytes": artifact.size_bytes,
                },
            )
        )

    def _scope(self) -> str:
        if self._organization_id is None:
            raise ReportRepositoryError("organization scope is required")
        return self._organization_id

    def _find_by_idempotency(
        self,
        session: Session,
        key: str,
    ) -> TestReportVersion | None:
        return session.scalar(
            select(TestReportVersion).where(
                TestReportVersion.organization_id == self._scope(),
                TestReportVersion.idempotency_key == key,
            )
        )

    @staticmethod
    def _validate_session(test_session: TestSession) -> None:
        if test_session.state not in {"completed", "archived"}:
            raise ReportSessionStateError(
                f"session state {test_session.state!r} is not reportable"
            )
        if test_session.started_at is None or test_session.completed_at is None:
            raise ReportSessionStateError(
                "reportable session has no committed start/completion boundary"
            )

    @staticmethod
    def _config_snapshot(
        session: Session,
        test_session: TestSession,
    ) -> SessionConfigSnapshot:
        statement = select(SessionConfigSnapshot).where(
            SessionConfigSnapshot.session_id == test_session.id
        )
        if test_session.active_config_snapshot_id is not None:
            statement = statement.where(
                SessionConfigSnapshot.id
                == test_session.active_config_snapshot_id
            )
        else:
            statement = statement.order_by(
                SessionConfigSnapshot.version.desc(),
                SessionConfigSnapshot.id.desc(),
            )
        snapshot = session.scalar(statement.limit(1))
        if snapshot is None:
            raise ReportSessionStateError(
                "reportable session has no configuration snapshot"
            )
        return snapshot

    @staticmethod
    def _next_version(session: Session, session_id: str) -> int:
        current = session.scalar(
            select(func.coalesce(func.max(TestReportVersion.version), 0))
            .where(TestReportVersion.session_id == session_id)
        )
        return int(current or 0) + 1

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

    def _audit_generation(
        self,
        session: Session,
        report: TestReportVersion,
        *,
        identity_id: str | None,
        actor_subject: str,
        actor_roles: frozenset[Role],
        reason: str | None,
    ) -> None:
        if self._security_repository is None:
            return
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=report.organization_id,
                actor_identity_id=identity_id,
                actor_subject=actor_subject,
                actor_roles=actor_roles,
                action="report.generated",
                entity_type="test_report_version",
                entity_id=report.id,
                after_snapshot={
                    "session_id": report.session_id,
                    "version": report.version,
                    "source_sha256": report.source_sha256,
                    "manifest_sha256": report.manifest_sha256,
                    "generator_version": report.generator_version,
                },
                reason=reason,
            ),
            session=session,
        )

    @staticmethod
    def _detach(session: Session, record: ReportRecord) -> ReportRecord:
        session.expunge(record.report)
        for artifact in record.artifacts:
            session.expunge(artifact)
        return record


def _artifact_rows(
    report_id: str,
    created_at: datetime,
    artifacts: tuple[tuple[ArtifactDescriptor, bytes], ...],
) -> list[TestReportArtifact]:
    return [
        TestReportArtifact(
            id=str(uuid4()),
            report_id=report_id,
            name=descriptor.name,
            media_type=descriptor.media_type,
            sha256=descriptor.sha256,
            size_bytes=descriptor.size_bytes,
            row_count=descriptor.row_count,
            content=content,
            created_at=created_at,
        )
        for descriptor, content in sorted(
            artifacts,
            key=lambda item: item[0].name,
        )
    ]


def _descriptor(value: ArtifactDescriptor) -> dict[str, Any]:
    return {
        "name": value.name,
        "media_type": value.media_type,
        "sha256": value.sha256,
        "size_bytes": value.size_bytes,
        "row_count": value.row_count,
    }


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _optional_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if len(normalized) != 64:
        raise ValueError(
            "expected_source_sha256 must be a SHA-256 hex digest"
        )
    try:
        int(normalized, 16)
    except ValueError as error:
        raise ValueError(
            "expected_source_sha256 must be a SHA-256 hex digest"
        ) from error
    return normalized
