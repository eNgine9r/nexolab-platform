from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reports.approval import ApprovalCommand
from app.reports.output_repository import ReportOutputRepository, SupersedeCommand
from app.reports.repository import ReportRepository
from app.security.authorization import Role
from app.security.models import SecurityAuditEvent
from app.security.repository import SecurityRepository
from tests.test_report_repository import build_database, generate, seed_session


def test_approval_audit_timestamps_are_json_safe_utc_strings() -> None:
    database = build_database()
    seed_session(database)
    security = SecurityRepository(database)
    source_repository = ReportRepository(
        database,
        security_repository=security,
    ).for_organization("organization-1")
    first = generate(source_repository, "report-request-1")
    second = generate(
        source_repository,
        "report-request-2",
        first.report.source_sha256,
    )
    outputs = ReportOutputRepository(
        database,
        security_repository=security,
    ).for_organization("organization-1")
    approved_at = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)

    outputs.approve(
        first.report.id,
        ApprovalCommand(
            idempotency_key="approve-report-1",
            actor_subject="manager-1",
            reason="Reviewed frozen evidence",
            expected_manifest_sha256=first.report.manifest_sha256,
            occurred_at=approved_at,
        ),
        actor_identity_id=None,
        actor_roles=frozenset({Role.LABORATORY_MANAGER}),
    )
    superseded_at = approved_at + timedelta(minutes=5)
    outputs.supersede(
        first.report.id,
        SupersedeCommand(
            idempotency_key="supersede-report-1",
            actor_subject="manager-1",
            reason="A later immutable report version replaces this protocol",
            expected_manifest_sha256=first.report.manifest_sha256,
            replacement_report_id=second.report.id,
            occurred_at=superseded_at,
        ),
        actor_identity_id=None,
        actor_roles=frozenset({Role.LABORATORY_MANAGER}),
    )

    with Session(database.engine) as session:
        approved = session.scalar(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.action == "report.approved"
            )
        )
        superseded = session.scalar(
            select(SecurityAuditEvent).where(
                SecurityAuditEvent.action == "report.superseded"
            )
        )

    assert approved is not None
    assert approved.after_snapshot is not None
    assert approved.after_snapshot["approved_at"] == approved_at.isoformat()
    assert superseded is not None
    assert superseded.after_snapshot is not None
    assert superseded.after_snapshot["superseded_at"] == superseded_at.isoformat()
