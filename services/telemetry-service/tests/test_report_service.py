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
from app.reports.service import ReportGenerationError, ReportService
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

FIXED_NOW = datetime(2026, 7, 26, 16, 0, tzinfo=UTC)


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
        organization = SecurityOrganization(
            id=organization_id,
            slug=organization_id,
            name=organization_id,
        )
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
        session.add(organization)
        session.flush()
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
        session.add(binding)
        session.add(snapshot)
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
            source="report-service-test",
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


def test_generate_persists_exact_hashed_evidence_and_replays_idempotently() -> None:
    database = build_database()
    seed_session(database)
    service = ReportService(database, clock=lambda: FIXED_NOW)

    generated = service.generate(
        organization_id="organization-1",
        session_id="session-1",
        idempotency_key="report-request-1",
        generated_by="engineer-1",
    )

    assert generated.replayed is False
    assert generated.report.version == 1
    assert generated.report.generated_by == "engineer-1"
    assert [artifact.name for artifact in generated.artifacts] == [
        "alerts.csv",
        "manifest.json",
        "source.json",
        "telemetry.csv",
    ]
    for artifact in generated.artifacts:
        assert artifact.sha256 == sha256_hex(artifact.content)
        assert artifact.size_bytes == len(artifact.content)

    artifacts = {artifact.name: artifact for artifact in generated.artifacts}
    assert artifacts["telemetry.csv"].row_count == 1
    assert artifacts["alerts.csv"].row_count == 0
    assert b"event-session-1" in artifacts["telemetry.csv"].content
    source = json.loads(artifacts["source.json"].content)
    assert source["counts"]["telemetry"] == 1
    assert source["session"]["organization_id"] == "organization-1"
    manifest = json.loads(artifacts["manifest.json"].content)
    assert manifest["report"]["source_sha256"] == generated.report.source_sha256
    assert generated.report.manifest_sha256 == artifacts["manifest.json"].sha256

    replay = service.generate(
        organization_id="organization-1",
        session_id="session-1",
        idempotency_key="report-request-1",
        generated_by="different-actor-is-not-authoritative-on-replay",
    )
    assert replay.replayed is True
    assert replay.report.id == generated.report.id
    assert [artifact.content for artifact in replay.artifacts] == [
        artifact.content for artifact in generated.artifacts
    ]

    with Session(database.engine) as session:
        assert session.scalar(select(func.count(TestReportVersion.id))) == 1


def test_new_idempotency_key_creates_monotonic_version_with_same_source_bytes() -> None:
    database = build_database()
    seed_session(database)
    service = ReportService(database, clock=lambda: FIXED_NOW)

    first = service.generate(
        organization_id="organization-1",
        session_id="session-1",
        idempotency_key="report-request-1",
        generated_by="engineer-1",
    )
    second = service.generate(
        organization_id="organization-1",
        session_id="session-1",
        idempotency_key="report-request-2",
        generated_by="engineer-1",
    )

    assert first.report.version == 1
    assert second.report.version == 2
    first_artifacts = {artifact.name: artifact.content for artifact in first.artifacts}
    second_artifacts = {artifact.name: artifact.content for artifact in second.artifacts}
    assert first_artifacts["source.json"] == second_artifacts["source.json"]
    assert first_artifacts["telemetry.csv"] == second_artifacts["telemetry.csv"]
    assert first_artifacts["alerts.csv"] == second_artifacts["alerts.csv"]


def test_running_session_is_rejected_before_artifacts_are_created() -> None:
    database = build_database()
    seed_session(database, state="running")
    service = ReportService(database, clock=lambda: FIXED_NOW)

    with pytest.raises(ReportGenerationError) as raised:
        service.generate(
            organization_id="organization-1",
            session_id="session-1",
            idempotency_key="report-request-1",
            generated_by="engineer-1",
        )

    assert raised.value.code == "report_session_not_terminal"
    assert service.list_reports(organization_id="organization-1") == []


def test_foreign_organization_cannot_discover_or_generate_session_report() -> None:
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
    service = ReportService(database, clock=lambda: FIXED_NOW)

    with pytest.raises(ReportGenerationError) as raised:
        service.generate(
            organization_id="organization-2",
            session_id="session-1",
            idempotency_key="foreign-report-request",
            generated_by="foreign-engineer",
        )

    assert raised.value.code == "report_session_not_found"
    assert service.list_reports(organization_id="organization-2") == []
    assert service.get_report(
        organization_id="organization-2",
        report_id="unknown",
    ) is None
