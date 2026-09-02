from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.commissioning.activation_client import (
    DeviceAgentActivationCommand,
    DeviceAgentActivationError,
    validate_activation_evidence,
    validate_activation_health,
)
from app.commissioning.activation_repository import (
    CommissioningActivationRepository,
    CommissioningPreflightStaleError,
)
from app.commissioning.activation_service import CommissioningActivationService
from app.commissioning.api import create_commissioning_router
from app.commissioning.repository import CommissioningRepository
from app.commissioning.models import (
    EquipmentCommissioningPreflightAttempt,
    EquipmentCommissioningSession,
)
from app.db import Database, TelemetryLatest
from app.model_registry import register_models
from app.refrigeration.controller_binding_repository import (
    PostgresRefrigerationControllerBindingRepository,
)
from app.refrigeration.models import RefrigerationControllerBinding, RefrigerationEquipmentRecord
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository

ORG = "00000000-0000-0000-0000-000000000001"
PROFILE = "embraco-sync-fc03-v1.00.04"


def _audit(action: str) -> AuditEventInput:
    return AuditEventInput(
        organization_id=ORG,
        actor_identity_id=None,
        actor_subject="engineer",
        actor_roles=frozenset({Role.ADMINISTRATOR}),
        action=action,
        entity_type="equipment_commissioning_session",
        entity_id="session-1",
        reason="test",
    )


def _equipment(now: datetime) -> RefrigerationEquipmentRecord:
    return RefrigerationEquipmentRecord(
        id="equipment-1",
        organization_id=ORG,
        code="EQ-1",
        name="Commissioning target",
        location="Lab",
        laboratory=None,
        zone=None,
        node_id="edge-01",
        climate_chamber_id=None,
        equipment_type="Холодильна вітрина",
        manufacturer="Test",
        model="Fixture",
        serial_number="fixture-1",
        temperature_class="Test",
        installed_at=None,
        serviced_at=None,
        lifecycle_status="active",
        status="offline",
        average_temperature_c=0.0,
        min_temperature_c=0.0,
        max_temperature_c=0.0,
        online_sensors=0,
        total_sensors=1,
        active_alarms=0,
        last_seen_at=None,
        version=1,
        created_by="test",
        created_at=now,
        updated_at=now,
        deleted_by=None,
        deleted_at=None,
    )


def _database(tmp_path: Path, *, preflight_age_seconds: float = 0.0) -> Database:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'activation.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG, slug="org", name="Organization")
    now = datetime.now(UTC)
    completed_at = now - timedelta(seconds=preflight_age_seconds)
    evidence = {
        "schema_version": 1,
        "result": "passed",
        "code": "preflight_passed",
        "evidence_level": "hardware_verified",
        "node_id": "edge-01",
        "bus_id": "rs485-main",
        "stable_transport_identifier": "/dev/serial/by-id/usb-test",
        "unit_id": 2,
        "profile_id": "embraco-sync",
        "profile_version": PROFILE,
        "read_method": "modbus_rtu_fc03",
        "function_codes": [3],
        "checks": [],
        "observations": [],
        "warnings": [],
        "duration_ms": 10,
        "modbus_writes": "none",
        "hardware_writes": "none",
    }
    with Session(database.engine) as session, session.begin():
        session.add(_equipment(now))
        session.add(
            EquipmentCommissioningSession(
                id="session-1",
                organization_id=ORG,
                create_idempotency_key="draft-1",
                create_fingerprint_sha256="0" * 64,
                lifecycle="verified",
                device_class="temperature-controller",
                manufacturer="Embraco",
                model="Sync",
                profile_id="embraco-sync",
                profile_version=PROFILE,
                transport_kind="modbus_rtu",
                node_id="edge-01",
                bus_id="rs485-main",
                stable_transport_identifier="/dev/serial/by-id/usb-test",
                unit_id=2,
                ip_address=None,
                target_equipment_key="equipment-1",
                blocked_reason=None,
                unsupported_reason=None,
                version=2,
                created_by="engineer",
                updated_by="engineer",
                created_at=now,
                updated_at=now,
                cancelled_at=None,
            )
        )
        session.add(
            EquipmentCommissioningPreflightAttempt(
                id="preflight-1",
                organization_id=ORG,
                session_id="session-1",
                idempotency_key="preflight-1",
                command_sha256="1" * 64,
                session_version=2,
                state="completed",
                result="passed",
                code="preflight_passed",
                evidence_level="hardware_verified",
                evidence=evidence,
                actor_subject="engineer",
                started_at=completed_at - timedelta(seconds=1),
                completed_at=completed_at,
            )
        )
    return database


class FakeActivationClient:
    def __init__(self, database: Database, *, persist_telemetry: bool = True) -> None:
        self.database = database
        self.persist_telemetry = persist_telemetry
        self.calls: list[DeviceAgentActivationCommand] = []

    def execute(self, command: DeviceAgentActivationCommand) -> dict[str, object]:
        self.calls.append(command)
        state = "rolled_back" if command.action == "rollback" else "active"
        if command.action == "activate" and self.persist_telemetry:
            now = datetime.now(UTC)
            with Session(self.database.engine) as session, session.begin():
                session.add(
                    TelemetryLatest(
                        sample_id=100,
                        event_id=str(uuid4()),
                        node_id="edge-01",
                        captured_at=now,
                        metric="refrigeration.control_state",
                        value=1.0,
                        unit="state",
                        quality="valid",
                        source="embraco-sync",
                        equipment_id="EMBRACO-2",
                        channel_id="2-control-state",
                        alarm=None,
                        raw_value=1,
                        raw_status=None,
                        stale_after_seconds=90.0,
                        received_at=now,
                    )
                )
        return {
            "schema_version": 1,
            "activation_id": command.activation_id,
            "state": state,
            "node_id": command.node_id,
            "bus_id": command.bus_id,
            "stable_transport_identifier": command.stable_transport_identifier,
            "unit_id": command.unit_id,
            "profile_id": command.profile_id,
            "profile_version": command.profile_version,
            "device_id": "embraco-2",
            "target_ids": ["embraco:2-control-state"],
            "registry_revision": 5,
            "telemetry_source": "embraco-sync",
            "telemetry_equipment_id": "EMBRACO-2",
            "polling_mode": "read_only_fc03",
            "modbus_writes": "none",
            "hardware_writes": "none",
            "reason": None,
        }

    def health(self, *, node_id: str, target_ids: list[str]) -> dict[str, object]:
        return {
            "status": "ok",
            "node_id": node_id,
            "mqtt_connected": True,
            "workers_healthy": True,
            "expected_bus_workers": 1,
            "active_bus_workers": 1,
            "target_ids": target_ids,
        }


def _service(database: Database, fake: FakeActivationClient) -> CommissioningActivationService:
    security = SecurityRepository(database)
    return CommissioningActivationService(
        repository=CommissioningActivationRepository(database, security_repository=security),
        client=fake,  # type: ignore[arg-type]
        controller_binding_repository=PostgresRefrigerationControllerBindingRepository(database),
        security_repository=security,
        freshness_seconds=60.0,
        verification_timeout_seconds=0.03,
        poll_interval_seconds=0.001,
    )


def test_activation_requires_fresh_matching_preflight(tmp_path: Path) -> None:
    database = _database(tmp_path, preflight_age_seconds=120.0)
    repository = CommissioningActivationRepository(database)
    with pytest.raises(CommissioningPreflightStaleError):
        repository.plan("session-1", organization_id=ORG, freshness_seconds=60.0)


def test_activation_persists_runtime_evidence_binding_and_replays(tmp_path: Path) -> None:
    database = _database(tmp_path)
    fake = FakeActivationClient(database)
    service = _service(database, fake)

    first = service.run(
        "session-1",
        organization_id=ORG,
        expected_version=2,
        idempotency_key="activate-1",
        actor_subject="engineer",
        started_audit_event=_audit("equipment.commissioning.activation.started"),
        completed_audit_event=_audit("equipment.commissioning.activation.completed"),
        binding_audit_event=_audit("equipment.controller_binding.updated"),
    )
    replay = service.run(
        "session-1",
        organization_id=ORG,
        expected_version=2,
        idempotency_key="activate-1",
        actor_subject="engineer",
        started_audit_event=_audit("equipment.commissioning.activation.started"),
        completed_audit_event=_audit("equipment.commissioning.activation.completed"),
        binding_audit_event=_audit("equipment.controller_binding.updated"),
    )

    assert first.state == replay.state == "active"
    assert first.id == replay.id
    assert len(fake.calls) == 1
    assert first.evidence is not None
    assert first.evidence["modbus_writes"] == "none"
    assert first.evidence["hardware_writes"] == "none"
    with Session(database.engine) as session:
        commissioning = session.get(EquipmentCommissioningSession, "session-1")
        assert commissioning is not None and commissioning.lifecycle == "active"
        binding = session.query(RefrigerationControllerBinding).one()
        assert binding.controller_equipment_id == "EMBRACO-2"
        assert binding.equipment_id == "equipment-1"


def test_activation_without_new_telemetry_rolls_back(tmp_path: Path) -> None:
    database = _database(tmp_path)
    fake = FakeActivationClient(database, persist_telemetry=False)
    service = _service(database, fake)
    result = service.run(
        "session-1",
        organization_id=ORG,
        expected_version=2,
        idempotency_key="activate-timeout",
        actor_subject="engineer",
        started_audit_event=_audit("equipment.commissioning.activation.started"),
        completed_audit_event=_audit("equipment.commissioning.activation.completed"),
        binding_audit_event=_audit("equipment.controller_binding.updated"),
    )

    assert result.state == "rolled_back"
    assert [call.action for call in fake.calls] == ["activate", "rollback"]
    assert result.evidence is not None
    assert result.evidence["modbus_writes"] == "none"
    assert result.evidence["hardware_writes"] == "none"
    with Session(database.engine) as session:
        commissioning = session.get(EquipmentCommissioningSession, "session-1")
        assert commissioning is not None and commissioning.lifecycle == "rolled_back"
        assert session.query(RefrigerationControllerBinding).count() == 0


def test_activation_http_plan_and_mutation_contract(tmp_path: Path) -> None:
    database = _database(tmp_path)
    fake = FakeActivationClient(database)
    service = _service(database, fake)
    security = SecurityRepository(database)
    app = FastAPI()
    app.include_router(
        create_commissioning_router(
            CommissioningRepository(database, security_repository=security),
            default_organization_id=ORG,
            activation_repository=service.repository,
            activation_service=service,
            activation_freshness_seconds=60.0,
        )
    )
    api = TestClient(app)

    plan = api.get("/api/v1/equipment/commissioning/sessions/session-1/activation-plan")
    activated = api.post(
        "/api/v1/equipment/commissioning/sessions/session-1/activation",
        headers={
            "If-Match": 'W/"commissioning-session-v2"',
            "Idempotency-Key": "http-activation-1",
        },
    )
    latest = api.get("/api/v1/equipment/commissioning/sessions/session-1/activation")

    assert plan.status_code == 200
    assert plan.json()["polling_mode"] == "read_only_fc03"
    assert "Modbus FC05/06/15/16 writes" in plan.json()["will_not_perform"]
    assert activated.status_code == 200
    assert activated.json()["state"] == "active"
    assert activated.json()["evidence"]["modbus_writes"] == "none"
    assert latest.json()["id"] == activated.json()["id"]


def test_activation_client_validation_rejects_write_or_health_drift() -> None:
    command = DeviceAgentActivationCommand(
        activation_id="activation-1",
        action="activate",
        node_id="edge-01",
        bus_id="rs485-main",
        stable_transport_identifier="/dev/serial/by-id/usb-test",
        unit_id=2,
        profile_id="embraco-sync",
        profile_version=PROFILE,
    )
    valid = {
        "schema_version": 1,
        "activation_id": "activation-1",
        "state": "active",
        "node_id": "edge-01",
        "bus_id": "rs485-main",
        "stable_transport_identifier": "/dev/serial/by-id/usb-test",
        "unit_id": 2,
        "profile_id": "embraco-sync",
        "profile_version": PROFILE,
        "device_id": "embraco-2",
        "target_ids": ["embraco:2-control-state"],
        "registry_revision": 5,
        "telemetry_source": "embraco-sync",
        "telemetry_equipment_id": "EMBRACO-2",
        "polling_mode": "read_only_fc03",
        "modbus_writes": "none",
        "hardware_writes": "none",
    }
    validate_activation_evidence(valid, command)
    with pytest.raises(DeviceAgentActivationError):
        validate_activation_evidence({**valid, "modbus_writes": "present"}, command)
    health = {
        "status": "ok",
        "node_id": "edge-01",
        "mqtt_connected": True,
        "acquisition": {"scheduler": {"workers_healthy": True, "targets": [{"target_id": "embraco:2-control-state"}]}},
    }
    validate_activation_health(health, node_id="edge-01", target_ids=["embraco:2-control-state"])
    with pytest.raises(DeviceAgentActivationError):
        validate_activation_health({**health, "mqtt_connected": False}, node_id="edge-01", target_ids=["embraco:2-control-state"])
