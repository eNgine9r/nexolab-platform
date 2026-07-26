from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, inspect, update
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session

from app.db import Base
from app.model_registry import register_models
from app.reports.immutability import ReportMutationError
from app.reports.models import TestReportArtifact, TestReportVersion
from app.security.models import SecurityOrganization
from app.sessions.models import SessionConfigSnapshot, TestSession

register_models()


def build_engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def seed_report(session: Session) -> tuple[TestReportVersion, TestReportArtifact]:
    captured_at = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    organization = SecurityOrganization(
        id="organization-1",
        slug="organization-1",
        name="Organization 1",
    )
    test_session = TestSession(
        id="session-1",
        organization_id=organization.id,
        create_idempotency_key="create-session-1",
        session_number="NX-2026-0001",
        node_id="edge-01",
        state="completed",
        title="Refrigeration showcase verification",
        test_object="K106",
        started_at=captured_at,
        completed_at=captured_at + timedelta(hours=2),
    )
    config_snapshot = SessionConfigSnapshot(
        id="snapshot-1",
        session_id=test_session.id,
        version=1,
        source="session_start",
        payload={"bindings": 1},
        content_sha256="a" * 64,
        created_by="engineer-1",
        captured_at=captured_at,
    )
    report = TestReportVersion(
        id="report-1",
        organization_id=organization.id,
        session_id=test_session.id,
        config_snapshot_id=config_snapshot.id,
        version=1,
        idempotency_key="generate-report-1",
        session_state="completed",
        source_started_at=captured_at,
        source_ended_at=captured_at + timedelta(hours=2),
        source_snapshot={"session_id": test_session.id},
        source_sha256="b" * 64,
        manifest_sha256="c" * 64,
        generator_version="reports-domain-v1",
        generated_by="engineer-1",
        generated_at=captured_at + timedelta(hours=3),
    )
    artifact = TestReportArtifact(
        id="artifact-1",
        report_id=report.id,
        name="telemetry.csv",
        media_type="text/csv",
        sha256="d" * 64,
        size_bytes=18,
        row_count=1,
        content=b"event_id,value\n1,2\n",
    )

    session.add(organization)
    session.flush()
    session.add(test_session)
    session.flush()
    session.add(config_snapshot)
    session.flush()
    session.add(report)
    session.flush()
    session.add(artifact)
    session.commit()
    return report, artifact


def test_report_schema_contains_scoped_version_and_artifact_constraints() -> None:
    engine = build_engine()
    inspector = inspect(engine)

    assert "test_report_versions" in inspector.get_table_names()
    assert "test_report_artifacts" in inspector.get_table_names()

    version_unique = {
        constraint["name"] for constraint in inspector.get_unique_constraints(
            "test_report_versions"
        )
    }
    artifact_unique = {
        constraint["name"] for constraint in inspector.get_unique_constraints(
            "test_report_artifacts"
        )
    }
    assert "uq_test_report_versions_session_version" in version_unique
    assert "uq_test_report_versions_organization_idempotency" in version_unique
    assert "uq_test_report_artifacts_report_name" in artifact_unique


def test_report_records_are_insertable_but_mapper_updates_are_rejected() -> None:
    engine = build_engine()
    with Session(engine, expire_on_commit=False) as session:
        report, _artifact = seed_report(session)
        report.generated_by = "different-actor"
        with pytest.raises(ReportMutationError, match="append-only"):
            session.commit()
        session.rollback()


def test_direct_sql_update_and_delete_are_blocked_by_database_triggers() -> None:
    engine = build_engine()
    with Session(engine) as session:
        report, artifact = seed_report(session)
        report_id = report.id
        artifact_id = artifact.id

    with engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                update(TestReportVersion)
                .where(TestReportVersion.id == report_id)
                .values(generated_by="different-actor")
            )

    with engine.begin() as connection:
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                delete(TestReportArtifact).where(TestReportArtifact.id == artifact_id)
            )


def test_report_version_and_idempotency_are_unique_within_scope() -> None:
    engine = build_engine()
    with Session(engine, expire_on_commit=False) as session:
        report, _artifact = seed_report(session)
        duplicate = TestReportVersion(
            id="report-2",
            organization_id=report.organization_id,
            session_id=report.session_id,
            config_snapshot_id=report.config_snapshot_id,
            version=report.version,
            idempotency_key="different-idempotency-key",
            session_state=report.session_state,
            source_started_at=report.source_started_at,
            source_ended_at=report.source_ended_at,
            source_snapshot=report.source_snapshot,
            source_sha256=report.source_sha256,
            manifest_sha256=report.manifest_sha256,
            generator_version=report.generator_version,
            generated_by=report.generated_by,
            generated_at=report.generated_at,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()
