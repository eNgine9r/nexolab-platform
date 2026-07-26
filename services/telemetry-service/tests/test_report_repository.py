from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Database, TelemetrySample
from app.model_registry import register_models
from app.reports.domain import sha256_hex
from app.reports.models import TestReportVersion
from app.reports.repository import (
    ReportRepository,
    ReportSessionNotFoundError,
    ReportSessionStateError,
    ReportSourceChangedError,
)
from app.security.authorization import Role
from app.security.models import SecurityOrganization
from app.sessions.models import (
    SessionChannelBinding,
    SessionConfigSnapshot,
    TestSession,
)
from app.sessions.telemetry_attribution import (
    ATTRIBUTION_RESOLVER_VERSION,
    TelemetrySessionContext,
)

register_models()


def build_database() -> Database:
    database = Database("sqlite+pysqlite:///:memory:")
    database.create_schema()
    return database


def seed_session(
    database: Database,
    *,
    state: str = "completed",
    organization_id: str = "organization-1",
    session_id: str = "session-1",
) -> None:
    started_at = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
    completed_at = started_at + timedelta(hours=2)
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(
                id=organization_id,
                slug=organization_id,
                name=organization_id,
            )
        )
        session.flush()
        test_session = TestSession(
            id=session_id,
            organization_id=organization_id,
            create_idempotency_key=f"create-{session_id}",
            session_number=f"NX-{session_id}",
            node_id="edge-01",
            state=state,
            title="Refrigeration showcase verification",
            test_object="K106",
            standard="ISO 23953",
            method="temperature distribution",
            started_at=started_at,
            completed_at=(completed_at if state in {"completed", "archived"} else None),
        )
        session.add(test_session)
        session.flush()
        binding = SessionChannelBinding(
            id=f"binding-{session_id}",
            session_id=session_id,
            node_id="edge-01",
            equipment_id="K106",
            channel_id="106-03",
            metric="temperature.probe",
            unit="degC",
            binding_metadata={"position": "front-left"},
            activated_at=started_at,
            released_at=(completed_at if state in {"completed", "archived"} else None),
        )
        snapshot = SessionConfigSnapshot(
            id=f"snapshot-{session_id}",
            session_id=session_id,
            version=1,
            source="session_start",
            payload={
                "bindings": [
                    {
                        "id": binding.id,
                        "node_id": binding.node_id,
                        "equipment_id": binding.equipment_id,
                        "channel_id": binding.channel_id,
                        "metric": binding.metric,
                    }
                ]
            },
            content_sha256="a" * 64,
            created_by="engineer-1",
            captured_at=started_at,
        )
        session.add_all([binding, snapshot])
        session.flush()
        test_session.active_config_snapshot_id = snapshot.id
        session.flush()
        sample = TelemetrySample(
            event_id=f"event-{session_id}",
            node_id="edge-01",
            captured_at=started_at + timedelta(minutes=10),
            metric="temperature.probe",
            value=3.75,
            unit="degC",
            quality="valid",
            source="report-repository-test",
            equipment_id="K106",
            channel_id="106-03",
            alarm=None,
            raw_value=375,
            raw_status=0,
            raw_payload={"register": 375},
            raw_payload_retained=True,
        )
        session.add(sample)
        session.flush()
        session.add(
            TelemetrySessionContext(
                telemetry_event_id=sample.event_id,
                session_id=session_id,
                stage_id=None,
                binding_id=binding.id,
                config_snapshot_id=snapshot.id,
                captured_at=sample.captured_at,
                resolver_version=ATTRIBUTION_RESOLVER_VERSION,
            )
        )
        session.commit()


def generate(repository: ReportRepository, key: str, expected: str | None = None):
    return repository.generate(
        "session-1",
        idempotency_key=key,
        generated_by="engineer-1",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
        expected_source_sha256=expected,
        reason="Controlled laboratory report generation",
    )


def test_repository_generates_exact_evidence_and_replays_idempotently() -> None:
    database = build_database()
    seed_session(database)
    repository = ReportRepository(database).for_organization("organization-1")

    created = generate(repository, "report-request-1")

    assert created.replayed is False
    assert created.report.version == 1
    assert [artifact.name for artifact in created.artifacts] == [
        "alert-transitions.csv",
        "manifest.json",
        "source-snapshot.json",
        "telemetry.csv",
    ]
    for artifact in created.artifacts:
        assert artifact.sha256 == sha256_hex(artifact.content)
        assert artifact.size_bytes == len(artifact.content)
    artifacts = {artifact.name: artifact for artifact in created.artifacts}
    assert artifacts["telemetry.csv"].row_count == 1
    assert artifacts["alert-transitions.csv"].row_count == 0
    assert b"event-session-1" in artifacts["telemetry.csv"].content
    source = json.loads(artifacts["source-snapshot.json"].content)
    assert source["organization_id"] == "organization-1"
    assert source["evidence"]["telemetry"]["row_count"] == 1
    manifest = json.loads(artifacts["manifest.json"].content)
    assert manifest["report"]["source_sha256"] == created.report.source_sha256
    assert created.report.manifest_sha256 == artifacts["manifest.json"].sha256

    replay = generate(repository, "report-request-1")
    assert replay.replayed is True
    assert replay.report.id == created.report.id
    assert [artifact.content for artifact in replay.artifacts] == [
        artifact.content for artifact in created.artifacts
    ]
    with Session(database.engine) as session:
        assert session.scalar(select(func.count(TestReportVersion.id))) == 1


def test_new_key_creates_monotonic_version_from_identical_source() -> None:
    database = build_database()
    seed_session(database)
    repository = ReportRepository(database).for_organization("organization-1")

    first = generate(repository, "report-request-1")
    second = generate(repository, "report-request-2", first.report.source_sha256)

    assert first.report.version == 1
    assert second.report.version == 2
    first_artifacts = {artifact.name: artifact.content for artifact in first.artifacts}
    second_artifacts = {artifact.name: artifact.content for artifact in second.artifacts}
    assert first_artifacts["source-snapshot.json"] == second_artifacts[
        "source-snapshot.json"
    ]
    assert first_artifacts["telemetry.csv"] == second_artifacts["telemetry.csv"]
    assert first_artifacts["alert-transitions.csv"] == second_artifacts[
        "alert-transitions.csv"
    ]


def test_running_session_and_changed_source_digest_are_rejected() -> None:
    running_database = build_database()
    seed_session(running_database, state="running")
    running_repository = ReportRepository(running_database).for_organization(
        "organization-1"
    )
    with pytest.raises(ReportSessionStateError):
        generate(running_repository, "running-report")

    completed_database = build_database()
    seed_session(completed_database)
    completed_repository = ReportRepository(completed_database).for_organization(
        "organization-1"
    )
    with pytest.raises(ReportSourceChangedError):
        generate(completed_repository, "changed-source", "f" * 64)
    assert completed_repository.list_reports().count == 0


def test_foreign_organization_cannot_discover_session_or_reports() -> None:
    database = build_database()
    seed_session(database)
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(
                id="organization-2",
                slug="organization-2",
                name="Organization 2",
            )
        )
        session.commit()
    foreign = ReportRepository(database).for_organization("organization-2")

    with pytest.raises(ReportSessionNotFoundError):
        generate(foreign, "foreign-report")
    assert foreign.list_reports().items == []
