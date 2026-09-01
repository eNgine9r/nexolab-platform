from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.commissioning.api import create_commissioning_router
from app.commissioning.preflight_client import (
    DeviceAgentPreflightCommand,
    DeviceAgentPreflightError,
    validate_preflight_evidence,
)
from app.commissioning.preflight_repository import CommissioningPreflightRepository
from app.commissioning.preflight_service import CommissioningPreflightService
from app.commissioning.repository import CommissioningRepository
from app.db import Database
from app.model_registry import register_models
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository

ORG = "00000000-0000-0000-0000-000000000001"


class FakePreflightClient:
    def __init__(self) -> None:
        self.calls: list[DeviceAgentPreflightCommand] = []
        self.error: DeviceAgentPreflightError | None = None
        self.result = "passed"
        self.code = "preflight_passed"
        self.evidence_level = "hardware_verified"

    def run(self, command: DeviceAgentPreflightCommand) -> dict[str, object]:
        self.calls.append(command)
        if self.error is not None:
            raise self.error
        return {
            "schema_version": 1,
            "result": self.result,
            "code": self.code,
            "evidence_level": self.evidence_level,
            "node_id": command.node_id,
            "bus_id": command.bus_id,
            "stable_transport_identifier": command.stable_transport_identifier,
            "unit_id": command.unit_id,
            "profile_id": command.profile_id,
            "profile_version": command.profile_version,
            "read_method": "modbus_rtu_fc03",
            "function_codes": [3],
            "checks": [{"key": "write_safety", "state": "passed", "detail": "writes none"}],
            "observations": [{"key": "control_state", "quality": "valid", "semantic": "cooling"}],
            "warnings": [],
            "duration_ms": 12,
            "modbus_writes": "none",
            "hardware_writes": "none",
        }


def _database(tmp_path: Path) -> tuple[Database, SecurityRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'preflight.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG, slug="org", name="Organization")
    now = datetime.now(UTC)
    with Session(database.engine) as session, session.begin():
        session.add(
            RefrigerationEquipmentRecord(
                id="equipment-1",
                organization_id=ORG,
                code="EQ-1",
                name="Commissioning target",
                location="Lab",
                laboratory=None,
                zone=None,
                node_id=None,
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
                average_temperature_c=0,
                min_temperature_c=0,
                max_temperature_c=0,
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
        )
    return database, security


def _app(database: Database, security: SecurityRepository, fake: FakePreflightClient) -> TestClient:
    service = CommissioningPreflightService(
        repository=CommissioningPreflightRepository(database, security_repository=security),
        client=fake,  # type: ignore[arg-type]
        deadline_seconds=5.0,
    )
    app = FastAPI()
    app.include_router(
        create_commissioning_router(
            CommissioningRepository(database, security_repository=security),
            SecurityDependencies(
                security,
                mode="disabled",
                authenticator=None,
                default_organization_id=ORG,
            ),
            default_organization_id=ORG,
            preflight_service=service,
        )
    )
    return TestClient(app)


def _ready_session(api: TestClient) -> tuple[str, str]:
    created = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json={
            "device_class": "temperature-controller",
            "manufacturer": "Embraco",
            "model": "Sync",
            "profile_id": "embraco-sync",
            "node_id": "edge-01",
            "bus_id": "rs485-embraco",
            "stable_transport_identifier": "/dev/serial/by-id/usb-embraco",
            "unit_id": 2,
            "target_equipment_key": "equipment-1",
        },
        headers={"Idempotency-Key": "draft-ready"},
    )
    assert created.status_code == 201
    assert created.json()["lifecycle"] == "ready_for_preflight"
    return created.json()["id"], created.headers["etag"]


def test_preflight_persists_and_replays_without_second_device_call(tmp_path: Path) -> None:
    database, security = _database(tmp_path)
    fake = FakePreflightClient()
    api = _app(database, security, fake)
    session_id, etag = _ready_session(api)
    headers = {"If-Match": etag, "Idempotency-Key": "preflight-1"}

    first = api.post(f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight", headers=headers)
    replay = api.post(f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight", headers=headers)
    latest = api.get(f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight")

    assert first.status_code == 200
    assert first.json()["result"] == "passed"
    assert first.json()["evidence"]["function_codes"] == [3]
    assert first.json()["evidence"]["modbus_writes"] == "none"
    assert first.json()["evidence"]["hardware_writes"] == "none"
    assert replay.json()["id"] == first.json()["id"]
    assert latest.json()["id"] == first.json()["id"]
    assert len(fake.calls) == 1

    restarted = _app(database, security, FakePreflightClient())
    persisted = restarted.get(f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight")
    assert persisted.status_code == 200
    assert persisted.json()["evidence_level"] == "hardware_verified"


def test_preflight_transport_failure_is_persisted_as_unverified_and_read_only(tmp_path: Path) -> None:
    database, security = _database(tmp_path)
    fake = FakePreflightClient()
    fake.error = DeviceAgentPreflightError("device_agent_unavailable", "agent unavailable")
    api = _app(database, security, fake)
    session_id, etag = _ready_session(api)

    response = api.post(
        f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight",
        headers={"If-Match": etag, "Idempotency-Key": "preflight-failed"},
    )

    assert response.status_code == 200
    assert response.json()["result"] == "failed"
    assert response.json()["code"] == "device_agent_unavailable"
    assert response.json()["evidence_level"] == "unverified"
    assert response.json()["evidence"]["modbus_writes"] == "none"
    assert response.json()["evidence"]["hardware_writes"] == "none"


def test_preflight_requires_current_version_and_ready_lifecycle(tmp_path: Path) -> None:
    database, security = _database(tmp_path)
    api = _app(database, security, FakePreflightClient())
    session_id, etag = _ready_session(api)

    stale = api.post(
        f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight",
        headers={"If-Match": 'W/"commissioning-session-v99"', "Idempotency-Key": "stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "commissioning_session_version_conflict"

    patched = api.patch(
        f"/api/v1/equipment/commissioning/sessions/{session_id}",
        json={"stable_transport_identifier": None},
        headers={"If-Match": etag},
    )
    assert patched.json()["lifecycle"] == "draft"
    blocked = api.post(
        f"/api/v1/equipment/commissioning/sessions/{session_id}/preflight",
        headers={"If-Match": patched.headers["etag"], "Idempotency-Key": "not-ready"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "commissioning_lifecycle_conflict"


def test_device_agent_client_rejects_public_origins() -> None:
    from app.commissioning.preflight_client import DeviceAgentPreflightClient

    DeviceAgentPreflightClient("http://edge-device-agent:8081")
    DeviceAgentPreflightClient("http://127.0.0.1:8081")
    with pytest.raises(ValueError):
        DeviceAgentPreflightClient("https://example.com")
    with pytest.raises(ValueError):
        DeviceAgentPreflightClient("http://8.8.8.8:8081")


def test_device_agent_evidence_validation_rejects_write_or_identity_drift() -> None:
    command = DeviceAgentPreflightCommand(
        node_id="edge-01",
        bus_id="rs485-main",
        stable_transport_identifier="/dev/serial/by-id/usb-test",
        unit_id=2,
        profile_id="embraco-sync",
        profile_version="embraco-sync-fc03-v1.00.04",
        deadline_seconds=5.0,
    )
    valid = FakePreflightClient().run(command)
    for change in (
        {"function_codes": [6]},
        {"modbus_writes": "present"},
        {"hardware_writes": "present"},
        {"unit_id": 3},
        {"profile_version": "wrong"},
    ):
        with pytest.raises(DeviceAgentPreflightError):
            validate_preflight_evidence({**valid, **change}, command)
