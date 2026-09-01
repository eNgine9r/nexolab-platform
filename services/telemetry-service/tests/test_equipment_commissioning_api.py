from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.commissioning.api import create_commissioning_router
from app.commissioning.repository import CommissioningRepository
from app.db import Database
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.authorization import AuthenticatedPrincipal, Permission, Role
from app.security.dependencies import AuthorizedRequest
from app.security.models import SecurityAuditEvent
from app.security.repository import SecurityRepository

ORG_A = "00000000-0000-0000-0000-000000000001"
ORG_B = "00000000-0000-0000-0000-000000000002"


def _database(tmp_path: Path) -> tuple[Database, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / 'commissioning.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG_A, slug="a", name="Organization A")
    security.provision_organization(organization_id=ORG_B, slug="b", name="Organization B")
    return database, security


def _client(tmp_path: Path) -> tuple[TestClient, Database]:
    database, security = _database(tmp_path)
    from app.security.dependencies import SecurityDependencies

    app = FastAPI()
    app.include_router(
        create_commissioning_router(
            CommissioningRepository(database, security_repository=security),
            SecurityDependencies(
                security,
                mode="disabled",
                authenticator=None,
                default_organization_id=ORG_A,
            ),
            default_organization_id=ORG_A,
        )
    )
    return TestClient(app), database


def _draft(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "device_class": "temperature-controller",
        "manufacturer": "Embraco",
        "model": "Sync",
        "profile_id": "embraco-sync",
        "node_id": None,
        "bus_id": None,
        "stable_transport_identifier": None,
        "unit_id": None,
        "target_equipment_key": None,
    }
    value.update(overrides)
    return value


def _equipment(
    database: Database,
    *,
    organization_id: str = ORG_A,
    equipment_id: str = "equipment-cool-jet",
    lifecycle_status: str = "active",
) -> str:
    now = datetime.now(UTC)
    with Session(database.engine) as session, session.begin():
        session.add(
            RefrigerationEquipmentRecord(
                id=equipment_id,
                organization_id=organization_id,
                code=f"TEST-{equipment_id}",
                name="Commissioning target",
                location="Test laboratory",
                laboratory=None,
                zone=None,
                node_id=None,
                climate_chamber_id=None,
                equipment_type="Холодильна вітрина",
                manufacturer="Test",
                model="Fixture",
                serial_number=equipment_id,
                temperature_class="Test",
                installed_at=None,
                serviced_at=None,
                lifecycle_status=lifecycle_status,
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
    return equipment_id


def test_supported_profile_catalog_is_read_only_and_exact() -> None:
    database = Database("sqlite:///:memory:")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(organization_id=ORG_A, slug="a", name="A")
    app = FastAPI()
    app.include_router(create_commissioning_router(CommissioningRepository(database, security_repository=security)))
    response = TestClient(app).get("/api/v1/equipment/commissioning/profiles")
    assert response.status_code == 200
    assert [(item["id"], item["version"], item["read_only"]) for item in response.json()["items"]] == [
        ("dixell-xjp60d", "dixell-xjp60d-fc03-v1", True),
        ("f-and-f-le01mp", "f-and-f-le01mp-fc03-v2", True),
        ("embraco-sync", "embraco-sync-fc03-v1.00.04", True),
    ]
    profile = TestClient(app).get("/api/v1/equipment/commissioning/profiles/embraco-sync")
    missing = TestClient(app).get("/api/v1/equipment/commissioning/profiles/unknown")
    assert profile.status_code == 200
    assert profile.json()["capability_status"] == "repository_supported_hardware_evidenced"
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "commissioning_profile_not_found"


def test_create_is_idempotent_and_rejects_key_reuse(tmp_path: Path) -> None:
    api, _ = _client(tmp_path)
    headers = {"Idempotency-Key": "draft-1", "X-Audit-Reason": "Commission new controller"}
    created = api.post("/api/v1/equipment/commissioning/sessions", json=_draft(), headers=headers)
    replay = api.post("/api/v1/equipment/commissioning/sessions", json=_draft(), headers=headers)
    conflict = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(model="Unknown"),
        headers=headers,
    )

    assert created.status_code == 201
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replay"] == "true"
    assert created.json()["id"] == replay.json()["id"]
    assert created.json()["lifecycle"] == "draft"
    assert created.headers["etag"] == 'W/"commissioning-session-v1"'
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "commissioning_idempotency_key_reused"


def test_draft_becomes_ready_only_when_read_only_intent_is_complete(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    target_equipment_id = _equipment(database)
    created = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(),
        headers={"Idempotency-Key": "ready-1"},
    )
    session_id = created.json()["id"]
    completed = api.patch(
        f"/api/v1/equipment/commissioning/sessions/{session_id}",
        json={
            "node_id": "edge-01",
            "bus_id": "rs485-embraco",
            "stable_transport_identifier": "/dev/serial/by-id/usb-CP2104-test",
            "unit_id": 2,
            "target_equipment_key": target_equipment_id,
        },
        headers={"If-Match": created.headers["etag"], "X-Audit-Reason": "Complete intent"},
    )
    stale = api.patch(
        f"/api/v1/equipment/commissioning/sessions/{session_id}",
        json={"unit_id": 3},
        headers={"If-Match": created.headers["etag"]},
    )

    assert completed.status_code == 200
    assert completed.json()["lifecycle"] == "ready_for_preflight"
    assert completed.json()["profile_version"] == "embraco-sync-fc03-v1.00.04"
    assert completed.headers["etag"] == 'W/"commissioning-session-v2"'
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "commissioning_session_version_conflict"

    with Session(database.engine) as session:
        actions = list(session.scalars(select(SecurityAuditEvent.action).order_by(SecurityAuditEvent.occurred_at)))
    assert "equipment.commissioning.created" in actions
    assert "equipment.commissioning.updated" in actions


def test_unstable_serial_path_blocks_readiness(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    target_equipment_id = _equipment(database)
    created = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(
            node_id="edge-01",
            bus_id="rs485-embraco",
            stable_transport_identifier="/dev/ttyUSB0",
            unit_id=2,
            target_equipment_key=target_equipment_id,
        ),
        headers={"Idempotency-Key": "unstable-path"},
    )

    assert created.status_code == 201
    assert created.json()["lifecycle"] == "blocked"
    assert "/dev/serial/by-id/" in created.json()["blocked_reason"]


def test_ready_draft_is_reported_blocked_after_target_is_retired(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    target_equipment_id = _equipment(database)
    created = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(
            node_id="edge-01",
            bus_id="rs485-embraco",
            stable_transport_identifier="/dev/serial/by-id/usb-CP2104-test",
            unit_id=2,
            target_equipment_key=target_equipment_id,
        ),
        headers={"Idempotency-Key": "retired-after-ready"},
    )
    with Session(database.engine) as session, session.begin():
        equipment = session.get(RefrigerationEquipmentRecord, (target_equipment_id, ORG_A))
        assert equipment is not None
        equipment.lifecycle_status = "retired"

    fetched = api.get(f"/api/v1/equipment/commissioning/sessions/{created.json()['id']}")
    listed = api.get("/api/v1/equipment/commissioning/sessions")

    assert created.json()["lifecycle"] == "ready_for_preflight"
    assert fetched.status_code == 200
    assert fetched.json()["lifecycle"] == "blocked"
    assert "unavailable" in fetched.json()["blocked_reason"]
    assert listed.json()["items"][0]["lifecycle"] == "blocked"


def test_invalid_cross_organization_and_retired_equipment_references_fail_closed(
    tmp_path: Path,
) -> None:
    api, database = _client(tmp_path)
    foreign_equipment_id = _equipment(
        database,
        organization_id=ORG_B,
        equipment_id="foreign-equipment",
    )
    retired_equipment_id = _equipment(
        database,
        equipment_id="retired-equipment",
        lifecycle_status="retired",
    )
    missing = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(target_equipment_key="missing-equipment"),
        headers={"Idempotency-Key": "missing-target"},
    )
    foreign = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(target_equipment_key=foreign_equipment_id),
        headers={"Idempotency-Key": "foreign-target"},
    )
    retired = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(target_equipment_key=retired_equipment_id),
        headers={"Idempotency-Key": "retired-target"},
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "commissioning_equipment_reference_invalid"
    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == "commissioning_equipment_reference_invalid"
    assert retired.status_code == 422
    assert retired.json()["detail"]["code"] == "commissioning_equipment_reference_invalid"


def test_unknown_and_mismatched_models_fail_closed(tmp_path: Path) -> None:
    api, _ = _client(tmp_path)
    unsupported = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(profile_id=None, manufacturer="Unknown", model="Mystery"),
        headers={"Idempotency-Key": "unsupported-1"},
    )
    blocked = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(model="XJP60D", profile_id="embraco-sync"),
        headers={"Idempotency-Key": "blocked-1"},
    )
    assert unsupported.status_code == 201
    assert unsupported.json()["lifecycle"] == "unsupported"
    assert unsupported.json()["unsupported_reason"] == "Unsupported / Profile required"
    assert blocked.status_code == 201
    assert blocked.json()["lifecycle"] == "blocked"
    assert "does not match" in blocked.json()["blocked_reason"]


def test_cancel_is_persistent_and_cancelled_session_is_read_only(tmp_path: Path) -> None:
    api, database = _client(tmp_path)
    created = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(),
        headers={"Idempotency-Key": "cancel-1"},
    )
    session_id = created.json()["id"]
    cancelled = api.post(
        f"/api/v1/equipment/commissioning/sessions/{session_id}/cancel",
        headers={"If-Match": created.headers["etag"], "X-Audit-Reason": "Operator cancelled"},
    )
    update = api.patch(
        f"/api/v1/equipment/commissioning/sessions/{session_id}",
        json={"node_id": "edge-02"},
        headers={"If-Match": cancelled.headers["etag"]},
    )
    reopened_repository = CommissioningRepository(database)
    persisted = reopened_repository.get_session(session_id, organization_id=ORG_A)

    assert cancelled.status_code == 200
    assert cancelled.json()["lifecycle"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None
    assert update.status_code == 409
    assert persisted.lifecycle == "cancelled"


def test_sessions_are_organization_scoped(tmp_path: Path) -> None:
    api, _ = _client(tmp_path)
    a = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(),
        headers={"Idempotency-Key": "org-a", "X-Organization-ID": ORG_A},
    )
    b = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(unit_id=5),
        headers={"Idempotency-Key": "org-b", "X-Organization-ID": ORG_B},
    )
    list_a = api.get("/api/v1/equipment/commissioning/sessions", headers={"X-Organization-ID": ORG_A})
    list_b = api.get("/api/v1/equipment/commissioning/sessions", headers={"X-Organization-ID": ORG_B})
    cross = api.get(
        f"/api/v1/equipment/commissioning/sessions/{a.json()['id']}",
        headers={"X-Organization-ID": ORG_B},
    )
    assert a.status_code == 201 and b.status_code == 201
    assert [item["id"] for item in list_a.json()["items"]] == [a.json()["id"]]
    assert [item["id"] for item in list_b.json()["items"]] == [b.json()["id"]]
    assert cross.status_code == 404


class DenyManageDependencies:
    def authorized_request(self, permission: Permission):
        def dependency() -> AuthorizedRequest:
            if permission == Permission.MANAGE_EQUIPMENT:
                raise HTTPException(status_code=403, detail={"code": "permission_denied"})
            return AuthorizedRequest(
                identity_id="viewer",
                principal=AuthenticatedPrincipal(
                    subject="viewer",
                    organization_id=ORG_A,
                    roles=frozenset({Role.VIEWER}),
                    granted_permissions=frozenset({Permission.READ_DASHBOARD}),
                ),
            )

        return dependency


def test_equipment_manage_permission_is_required_for_drafts(tmp_path: Path) -> None:
    database, security = _database(tmp_path)
    app = FastAPI()
    app.include_router(
        create_commissioning_router(
            CommissioningRepository(database, security_repository=security),
            DenyManageDependencies(),  # type: ignore[arg-type]
        )
    )
    api = TestClient(app)
    assert api.get("/api/v1/equipment/commissioning/profiles").status_code == 200
    denied = api.post(
        "/api/v1/equipment/commissioning/sessions",
        json=_draft(),
        headers={"Idempotency-Key": "denied"},
    )
    assert denied.status_code == 403
