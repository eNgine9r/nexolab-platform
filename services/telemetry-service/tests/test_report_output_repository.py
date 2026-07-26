from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from app.reports.approval import (
    ApprovalCommand,
    ReportApprovalDecision,
    ReportApprovalState,
)
from app.reports.models import TestReportApprovalEvent, TestReportRender
from app.reports.output_repository import (
    ReportOutputIdempotencyConflictError,
    ReportOutputNotFoundError,
    ReportOutputRepository,
    SupersedeCommand,
)
from app.security.authorization import Role
from test_report_repository import build_database, generate, seed_session


ROLES = frozenset({Role.ENGINEER})


def test_render_repository_persists_byte_stable_xlsx_and_pdf_with_exact_replay() -> None:
    database = build_database()
    seed_session(database)
    report_repository = ReportOutputRepository(database).for_organization(
        "organization-1"
    )
    generated = generate(
        __import__("app.reports.repository", fromlist=["ReportRepository"])
        .ReportRepository(database)
        .for_organization("organization-1"),
        "report-request-1",
    )

    xlsx = report_repository.render(
        generated.report.id,
        format_name="xlsx",
        idempotency_key="render-xlsx-1",
        rendered_by="engineer-1",
        actor_identity_id=None,
        actor_roles=ROLES,
        expected_manifest_sha256=generated.report.manifest_sha256,
        reason="Controlled XLSX render",
    )
    replay = report_repository.render(
        generated.report.id,
        format_name="xlsx",
        idempotency_key="render-xlsx-1",
        rendered_by="engineer-1",
        actor_identity_id=None,
        actor_roles=ROLES,
        expected_manifest_sha256=generated.report.manifest_sha256,
    )
    pdf = report_repository.render(
        generated.report.id,
        format_name="pdf",
        idempotency_key="render-pdf-1",
        rendered_by="engineer-1",
        actor_identity_id=None,
        actor_roles=ROLES,
        expected_manifest_sha256=generated.report.manifest_sha256,
    )

    assert xlsx.replayed is False
    assert replay.replayed is True
    assert replay.render.id == xlsx.render.id
    assert replay.render.content == xlsx.render.content
    assert xlsx.render.artifact_name == "report.xlsx"
    assert pdf.render.artifact_name == "protocol.pdf"
    assert pdf.render.content.startswith(b"%PDF-")
    with Session(database.engine) as session:
        assert session.scalar(select(func.count(TestReportRender.id))) == 2


def test_approval_event_stream_replays_and_supersedes_without_mutating_report() -> None:
    database = build_database()
    seed_session(database)
    source_repository = (
        __import__("app.reports.repository", fromlist=["ReportRepository"])
        .ReportRepository(database)
        .for_organization("organization-1")
    )
    first = generate(source_repository, "report-request-1")
    second = generate(
        source_repository,
        "report-request-2",
        first.report.source_sha256,
    )
    repository = ReportOutputRepository(database).for_organization("organization-1")
    approved_at = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    approval = ApprovalCommand(
        idempotency_key="approve-report-1",
        actor_subject="manager-1",
        reason="Reviewed frozen evidence",
        expected_manifest_sha256=first.report.manifest_sha256,
        occurred_at=approved_at,
    )

    created = repository.approve(
        first.report.id,
        approval,
        actor_identity_id=None,
        actor_roles=frozenset({Role.MANAGER}),
    )
    replay = repository.approve(
        first.report.id,
        approval,
        actor_identity_id=None,
        actor_roles=frozenset({Role.MANAGER}),
    )

    assert created.decision is ReportApprovalDecision.APPROVE
    assert created.snapshot.state is ReportApprovalState.APPROVED
    assert replay.decision is ReportApprovalDecision.REPLAY
    assert replay.event.id == created.event.id
    with pytest.raises(ReportOutputIdempotencyConflictError):
        repository.approve(
            first.report.id,
            ApprovalCommand(
                idempotency_key=approval.idempotency_key,
                actor_subject=approval.actor_subject,
                reason="Changed reason",
                expected_manifest_sha256=approval.expected_manifest_sha256,
                occurred_at=approval.occurred_at,
            ),
            actor_identity_id=None,
            actor_roles=frozenset({Role.MANAGER}),
        )

    superseded = repository.supersede(
        first.report.id,
        SupersedeCommand(
            idempotency_key="supersede-report-1",
            actor_subject="manager-1",
            reason="A later immutable report version replaces this protocol",
            expected_manifest_sha256=first.report.manifest_sha256,
            replacement_report_id=second.report.id,
            occurred_at=approved_at + timedelta(minutes=5),
        ),
        actor_identity_id=None,
        actor_roles=frozenset({Role.MANAGER}),
    )

    assert superseded.decision is ReportApprovalDecision.SUPERSEDE
    assert superseded.snapshot.state is ReportApprovalState.SUPERSEDED
    assert superseded.snapshot.approved_by == "manager-1"
    assert superseded.snapshot.superseded_by_report_id == second.report.id
    assert repository.approval_snapshot(second.report.id).state is (
        ReportApprovalState.GENERATED
    )
    with Session(database.engine) as session:
        events = list(
            session.scalars(
                select(TestReportApprovalEvent).order_by(
                    TestReportApprovalEvent.occurred_at
                )
            )
        )
        assert [event.event_type for event in events] == ["approved", "superseded"]


def test_render_and_approval_records_are_append_only_at_database_boundary() -> None:
    database = build_database()
    seed_session(database)
    source_repository = (
        __import__("app.reports.repository", fromlist=["ReportRepository"])
        .ReportRepository(database)
        .for_organization("organization-1")
    )
    generated = generate(source_repository, "report-request-1")
    repository = ReportOutputRepository(database).for_organization("organization-1")
    rendered = repository.render(
        generated.report.id,
        format_name="xlsx",
        idempotency_key="render-xlsx-1",
        rendered_by="engineer-1",
        actor_identity_id=None,
        actor_roles=ROLES,
    )
    approved = repository.approve(
        generated.report.id,
        ApprovalCommand(
            idempotency_key="approve-report-1",
            actor_subject="manager-1",
            reason="Approved",
            expected_manifest_sha256=generated.report.manifest_sha256,
            occurred_at=datetime(2026, 7, 26, 20, 0, tzinfo=UTC),
        ),
        actor_identity_id=None,
        actor_roles=frozenset({Role.MANAGER}),
    )

    with database.engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                update(TestReportRender)
                .where(TestReportRender.id == rendered.render.id)
                .values(rendered_by="different-actor")
            )
    with database.engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                delete(TestReportApprovalEvent).where(
                    TestReportApprovalEvent.id == approved.event.id
                )
            )


def test_foreign_organization_cannot_render_or_discover_approval_state() -> None:
    database = build_database()
    seed_session(database)
    generated = generate(
        __import__("app.reports.repository", fromlist=["ReportRepository"])
        .ReportRepository(database)
        .for_organization("organization-1"),
        "report-request-1",
    )
    foreign = ReportOutputRepository(database).for_organization("organization-2")

    with pytest.raises(ReportOutputNotFoundError):
        foreign.render(
            generated.report.id,
            format_name="xlsx",
            idempotency_key="foreign-render",
            rendered_by="foreign-user",
            actor_identity_id=None,
            actor_roles=ROLES,
        )
    with pytest.raises(ReportOutputNotFoundError):
        foreign.approval_snapshot(generated.report.id)
