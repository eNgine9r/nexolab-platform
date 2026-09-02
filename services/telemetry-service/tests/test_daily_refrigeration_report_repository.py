from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts.models import AlertInstance, AlertRule, AlertRuleVersion, AlertTransition
from app.daily_reports.domain import TelemetryPoint
from app.daily_reports.immutability import DailyReportSnapshotMutationError
from app.daily_reports.repository import DailyReportGenerationError, DailyReportRepository
from app.daily_reports.schemas import DailyReportProfileWrite
from app.db import Database, TelemetrySample
from app.model_registry import register_models
from app.nodes.models import CentralNode
from app.refrigeration.models import (
    EquipmentSensorBinding,
    RefrigerationControllerBinding,
    RefrigerationEquipmentRecord,
)
from app.security.authorization import Role
from app.security.models import SecurityAuditEvent, SecurityOrganization
from app.security.repository import SecurityRepository

register_models()

ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
REPORT_DATE = date(2026, 9, 2)
WINDOW_START = datetime(2026, 9, 1, 16, 50, tzinfo=UTC)
WINDOW_END = datetime(2026, 9, 2, 4, 50, tzinfo=UTC)


def telemetry(
    *,
    captured_at: datetime,
    equipment_id: str,
    channel_id: str,
    metric: str,
    value: float | None,
    unit: str,
    quality: str = "valid",
    source: str = "test",
) -> TelemetrySample:
    return TelemetrySample(
        event_id=str(uuid4()),
        node_id="edge-01",
        captured_at=captured_at,
        metric=metric,
        value=value,
        unit=unit,
        quality=quality,
        source=source,
        equipment_id=equipment_id,
        channel_id=channel_id,
        alarm=None,
        raw_value=None,
        raw_status=None,
        raw_payload={},
        raw_payload_retained=True,
    )


def build_database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'daily-report.db'}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add(
            SecurityOrganization(
                id=ORGANIZATION_ID,
                slug="default",
                name="Default organization",
            )
        )
        now = datetime.now(UTC)
        session.add(
            CentralNode(
                id=str(uuid4()),
                organization_id=ORGANIZATION_ID,
                node_id="edge-01",
                display_name="Edge 01",
                state="active",
                created_by="test-suite",
            )
        )
        session.add(
            RefrigerationEquipmentRecord(
                id="showcase-1",
                organization_id=ORGANIZATION_ID,
                code="TEST-SHOWCASE",
                name="Test refrigeration showcase",
                location="Test lab",
                laboratory="Test lab",
                zone=None,
                node_id="edge-01",
                climate_chamber_id=None,
                equipment_type="Холодильна вітрина",
                manufacturer="Test manufacturer",
                model="Test model",
                serial_number="TEST-0001",
                temperature_class="M1",
                installed_at=None,
                serviced_at=None,
                lifecycle_status="active",
                status="normal",
                average_temperature_c=0.0,
                min_temperature_c=0.0,
                max_temperature_c=0.0,
                online_sensors=2,
                total_sensors=2,
                active_alarms=0,
                last_seen_at=WINDOW_END,
                version=1,
                created_by="test-suite",
                created_at=now,
                updated_at=now,
                deleted_by=None,
                deleted_at=None,
            )
        )
        session.flush()
        session.add_all(
            [
                EquipmentSensorBinding(
                    id=str(uuid4()),
                    organization_id=ORGANIZATION_ID,
                    equipment_id="showcase-1",
                    node_id="edge-01",
                    channel_id="M1",
                    slot_key="front-1-1",
                    label="M1",
                    side="front",
                    shelf=1,
                    position=1,
                    version=1,
                    bound_by="test-suite",
                    bound_at=WINDOW_START - timedelta(days=1),
                ),
                EquipmentSensorBinding(
                    id=str(uuid4()),
                    organization_id=ORGANIZATION_ID,
                    equipment_id="showcase-1",
                    node_id="edge-01",
                    channel_id="M2",
                    slot_key="front-1-2",
                    label="M2",
                    side="front",
                    shelf=1,
                    position=2,
                    version=1,
                    bound_by="test-suite",
                    bound_at=WINDOW_START - timedelta(days=1),
                ),
            ]
        )
        session.add(
            RefrigerationControllerBinding(
                id=str(uuid4()),
                organization_id=ORGANIZATION_ID,
                equipment_id="showcase-1",
                node_id="edge-01",
                controller_family="embraco",
                controller_equipment_id="EMBRACO-2",
                unit_id=2,
                profile_version="embraco-sync-fc03-v1.00.04",
                bound_by="test-suite",
                bound_at=WINDOW_START - timedelta(days=1),
                unbound_by=None,
                unbound_at=None,
            )
        )
        session.add_all(
            [
                telemetry(
                    captured_at=WINDOW_START + timedelta(hours=1),
                    equipment_id="K108",
                    channel_id="M1",
                    metric="temperature.probe",
                    value=-5.0,
                    unit="degC",
                ),
                telemetry(
                    captured_at=WINDOW_END - timedelta(seconds=30),
                    equipment_id="K108",
                    channel_id="M1",
                    metric="temperature.probe",
                    value=0.3,
                    unit="degC",
                ),
                telemetry(
                    captured_at=WINDOW_START + timedelta(hours=2),
                    equipment_id="K108",
                    channel_id="M2",
                    metric="temperature.probe",
                    value=20.0,
                    unit="degC",
                ),
                telemetry(
                    captured_at=WINDOW_END - timedelta(seconds=30),
                    equipment_id="K108",
                    channel_id="M2",
                    metric="temperature.probe",
                    value=11.0,
                    unit="degC",
                ),
            ]
        )
        for index in range(25):
            captured_at = WINDOW_START + timedelta(minutes=30 * index)
            speed = 3000.0 if index < 12 else 0.0
            control_state = 3.0 if 4 <= index < 6 else 1.0
            session.add_all(
                [
                    telemetry(
                        captured_at=captured_at,
                        equipment_id="EMBRACO-2",
                        channel_id="2-compressor-speed",
                        metric="compressor.speed",
                        value=speed,
                        unit="rpm",
                        source="embraco-sync",
                    ),
                    telemetry(
                        captured_at=captured_at,
                        equipment_id="EMBRACO-2",
                        channel_id="2-control-state",
                        metric="refrigeration.control_state",
                        value=control_state,
                        unit="state",
                        source="embraco-sync",
                    ),
                ]
            )
        for index in range(13):
            session.add(
                telemetry(
                    captured_at=WINDOW_START + timedelta(hours=index),
                    equipment_id="METER-1",
                    channel_id="energy",
                    metric="electrical.energy.active",
                    value=100.0 + index * 0.5,
                    unit="kWh",
                    source="le01mp",
                )
            )
        session.commit()
    return database


def profile_payload() -> DailyReportProfileWrite:
    return DailyReportProfileWrite.model_validate(
        {
            "name": "Morning report",
            "equipment_id": "showcase-1",
            "m_packet_channels": [
                {
                    "node_id": "edge-01",
                    "equipment_id": "K108",
                    "channel_id": "M1",
                    "metric": "temperature.probe",
                    "label": "M1",
                },
                {
                    "node_id": "edge-01",
                    "equipment_id": "K108",
                    "channel_id": "M2",
                    "metric": "temperature.probe",
                    "label": "M2",
                },
            ],
            "temperature_min_c": -1.0,
            "temperature_max_c": 12.0,
            "energy_source": {
                "node_id": "edge-01",
                "equipment_id": "METER-1",
                "channel_id": "energy",
                "metric": "electrical.energy.active",
            },
        }
    )


def create_profile(repository: DailyReportRepository):
    return repository.create_profile(
        profile_payload(),
        actor_subject="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )


def test_snapshot_is_idempotent_and_contains_only_evidence_backed_morning_metrics(
    tmp_path: Path,
) -> None:
    database = build_database(tmp_path)
    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)

    first = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )
    replay = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.snapshot.id == first.snapshot.id
    payload = first.snapshot.payload
    assert first.snapshot.status == "normal"
    assert payload["m_packets"]["minimum_c"] == pytest.approx(0.3)
    assert payload["m_packets"]["maximum_c"] == pytest.approx(11.0)
    assert payload["m_packets"]["valid_channels"] == 2
    assert payload["m_packets"]["configured_channels"] == 2
    assert payload["compressor"]["duty_percent"] == pytest.approx(50.0)
    assert payload["compressor"]["coverage_percent"] == pytest.approx(100.0)
    assert payload["energy"]["interval_kwh"] == pytest.approx(6.0)
    assert payload["defrost"] == {
        "status": "available",
        "duration_seconds": pytest.approx(3600.0),
    }
    assert payload["refrigeration_circuit"]["superheat"] == {
        "reason": "not_implemented",
        "status": "unavailable",
    }
    assert payload["controller"]["setpoint"] == {
        "reason": "unverified_semantics",
        "status": "unavailable",
    }
    assert len(first.snapshot.payload_sha256) == 64


def test_missing_m_packet_and_energy_discontinuity_fail_closed(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    with Session(database.engine) as session:
        energy_rows = list(
            session.query(TelemetrySample)
            .filter(TelemetrySample.equipment_id == "METER-1")
            .order_by(TelemetrySample.captured_at)
        )
        energy_rows[7].value = 10.0
        session.query(TelemetrySample).filter(TelemetrySample.channel_id == "M2").delete()
        session.commit()

    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)
    result = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )

    assert result.snapshot.status == "incomplete"
    assert result.snapshot.payload["m_packets"]["valid_channels"] == 1
    assert result.snapshot.payload["energy"] == {
        "reason": "counter_discontinuity",
        "status": "unavailable",
    }
    assert set(result.snapshot.payload["quality"]["reasons"]) == {
        "energy_evidence_unavailable",
        "m_packet_coverage_incomplete",
    }


def test_snapshot_rows_are_append_only(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)
    generated = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )

    with Session(database.engine) as session:
        snapshot = session.get(type(generated.snapshot), generated.snapshot.id)
        assert snapshot is not None
        snapshot.status = "attention"
        with pytest.raises(DailyReportSnapshotMutationError):
            session.commit()


def test_profile_and_snapshot_mutations_emit_local_security_audit(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    repository = DailyReportRepository(
        database, security_repository=SecurityRepository(database)
    ).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)
    repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
        reason="morning report acceptance",
    )

    with Session(database.engine) as session:
        actions = list(
            session.scalars(
                select(SecurityAuditEvent.action).order_by(SecurityAuditEvent.occurred_at)
            )
        )
    assert "daily_report.profile.created" in actions
    assert "daily_report.snapshot.generated" in actions


def test_current_controller_state_does_not_hide_newer_invalid_evidence() -> None:
    points = [
        TelemetryPoint(
            captured_at=WINDOW_END - timedelta(seconds=60),
            value=1.0,
            quality="valid",
            event_id="valid",
        ),
        TelemetryPoint(
            captured_at=WINDOW_END - timedelta(seconds=30),
            value=None,
            quality="communication_error",
            event_id="invalid",
        ),
    ]

    assert DailyReportRepository._current_state(points, WINDOW_END) is None


def test_catch_up_snapshot_reconstructs_alert_state_at_report_end(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    triggered_at = WINDOW_END - timedelta(hours=1)
    resolved_at = WINDOW_END + timedelta(hours=1)
    rule_id = str(uuid4())
    version_id = str(uuid4())
    alert_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        rule = AlertRule(
            id=rule_id,
            organization_id=ORGANIZATION_ID,
            name="Morning alarm",
            description=None,
            enabled=True,
            severity="alarm",
            node_id="edge-01",
            equipment_id="showcase-1",
            channel_id="cabinet",
            metric="temperature.probe",
            session_id=None,
            current_version=1,
            created_by="test-suite",
            created_at=now,
            updated_at=now,
        )
        version = AlertRuleVersion(
            id=version_id,
            rule_id=rule_id,
            version=1,
            condition="threshold_high",
            trigger_threshold=10.0,
            clear_threshold=9.0,
            minimum_duration_seconds=0,
            clear_duration_seconds=0,
            debounce_seconds=0,
            cooldown_seconds=0,
            configuration={},
            created_by="test-suite",
            created_at=now,
        )
        alert = AlertInstance(
            id=alert_id,
            organization_id=ORGANIZATION_ID,
            rule_id=rule_id,
            rule_version_id=version_id,
            resource_key="edge-01:showcase-1:cabinet:temperature.probe",
            node_id="edge-01",
            equipment_id="showcase-1",
            channel_id="cabinet",
            metric="temperature.probe",
            state="resolved",
            severity="alarm",
            trigger_value=12.0,
            trigger_threshold=10.0,
            clear_threshold=9.0,
            maximum_deviation=2.0,
            first_event_id="trigger-event",
            last_event_id="resolve-event",
            session_id=None,
            stage_id=None,
            binding_id=None,
            context={},
            triggered_at=triggered_at,
            acknowledged_at=None,
            resolved_at=resolved_at,
            closed_at=None,
            lock_version=2,
            created_at=triggered_at,
            updated_at=resolved_at,
        )
        trigger = AlertTransition(
            id=str(uuid4()),
            alert_id=alert_id,
            event_type="triggered",
            previous_state=None,
            next_state="active",
            actor_id="alert-engine",
            actor_source="system",
            reason=None,
            idempotency_key="trigger-transition",
            payload={},
            occurred_at=triggered_at,
            inserted_at=triggered_at,
        )
        resolve = AlertTransition(
            id=str(uuid4()),
            alert_id=alert_id,
            event_type="resolved",
            previous_state="active",
            next_state="resolved",
            actor_id="alert-engine",
            actor_source="system",
            reason=None,
            idempotency_key="resolve-transition",
            payload={},
            occurred_at=resolved_at,
            inserted_at=resolved_at,
        )
        session.add_all([rule, version, alert, trigger, resolve])
        session.commit()

    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)
    result = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )

    alerts = result.snapshot.payload["alerts"]
    assert result.snapshot.status == "critical"
    assert alerts["active_count"] == 1
    assert alerts["active_severities"] == ["alarm"]
    assert alerts["items"][0]["state"] == "active"
    assert alerts["items"][0]["resolved_at"] is None


def test_profile_rejects_unbound_m_packet_channel(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    data = profile_payload().model_dump()
    data["m_packet_channels"][0]["channel_id"] = "UNBOUND"

    with pytest.raises(ValueError, match="actively bound"):
        repository.create_profile(
            DailyReportProfileWrite.model_validate(data),
            actor_subject="engineer-test",
            actor_identity_id=None,
            actor_roles=frozenset({Role.ENGINEER}),
        )


def test_profile_rejects_source_node_without_unique_org_ownership(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    data = profile_payload().model_dump()
    data["energy_source"]["node_id"] = "foreign-edge"

    with pytest.raises(ValueError, match="not uniquely owned"):
        repository.create_profile(
            DailyReportProfileWrite.model_validate(data),
            actor_subject="engineer-test",
            actor_identity_id=None,
            actor_roles=frozenset({Role.ENGINEER}),
        )


def test_sparse_controller_evidence_marks_snapshot_incomplete(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    with Session(database.engine) as session:
        session.query(TelemetrySample).filter(
            TelemetrySample.equipment_id == "EMBRACO-2"
        ).delete(synchronize_session=False)
        for offset_seconds, speed in ((60, 3000.0), (30, 0.0), (0, 0.0)):
            captured_at = WINDOW_END - timedelta(seconds=offset_seconds)
            session.add_all(
                [
                    telemetry(
                        captured_at=captured_at,
                        equipment_id="EMBRACO-2",
                        channel_id="2-compressor-speed",
                        metric="compressor.speed",
                        value=speed,
                        unit="rpm",
                        source="embraco-sync",
                    ),
                    telemetry(
                        captured_at=captured_at,
                        equipment_id="EMBRACO-2",
                        channel_id="2-control-state",
                        metric="refrigeration.control_state",
                        value=1.0,
                        unit="state",
                        source="embraco-sync",
                    ),
                ]
            )
        session.commit()

    repository = DailyReportRepository(database).for_organization(ORGANIZATION_ID)
    profile = create_profile(repository)
    result = repository.generate(
        profile.id,
        local_report_date=REPORT_DATE,
        generated_by="engineer-test",
        actor_identity_id=None,
        actor_roles=frozenset({Role.ENGINEER}),
    )

    assert result.snapshot.status == "incomplete"
    reasons = set(result.snapshot.payload["quality"]["reasons"])
    assert "compressor_coverage_incomplete" in reasons
    assert "defrost_coverage_incomplete" in reasons
    assert result.snapshot.payload["controller"]["status"] == "available"


def test_future_snapshot_generation_fails_before_immutable_insert(tmp_path: Path) -> None:
    database = build_database(tmp_path)
    fixed_now = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
    repository = DailyReportRepository(database, clock=lambda: fixed_now).for_organization(
        ORGANIZATION_ID
    )
    profile = create_profile(repository)
    future_date = date(2026, 9, 2)

    with pytest.raises(DailyReportGenerationError, match="before its scheduled time"):
        repository.generate(
            profile.id,
            local_report_date=future_date,
            generated_by="engineer-test",
            actor_identity_id=None,
            actor_roles=frozenset({Role.ENGINEER}),
        )

    assert repository.list_snapshots(profile_id=profile.id).count == 0
