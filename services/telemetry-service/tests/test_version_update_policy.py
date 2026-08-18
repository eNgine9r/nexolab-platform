from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import Database
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository
from app.version_management import VersionManagementStore, create_version_management_router


SECRET = "version-update-policy-test-secret-with-sufficient-length"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": "version-update-tests",
            "aud": "nexolab-api",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


def client(tmp_path: Path) -> tuple[TestClient, VersionManagementStore, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / 'security.db'}")
    database.create_schema()
    repository = SecurityRepository(database)
    repository.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab",
        name="NEXOLAB",
    )
    for subject, role in (("admin", Role.ADMINISTRATOR), ("engineer", Role.ENGINEER)):
        repository.provision_membership(
            organization_id=ORGANIZATION_ID,
            claims=VerifiedIdentityClaims(provider="test", subject=subject),
            roles={role},
        )
    dependencies = SecurityDependencies(
        repository,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer="version-update-tests",
            audience="nexolab-api",
            provider="test",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    store = VersionManagementStore(tmp_path / "versions")
    app = FastAPI()
    app.include_router(create_version_management_router(store, dependencies, repository))
    return TestClient(app), store, repository


def test_snapshot_defaults_automatic_updates_off_without_host_state(tmp_path: Path) -> None:
    api, _, _ = client(tmp_path)

    response = api.get("/api/v1/system/version", headers=headers("admin"))

    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["update_policy"] == {
        "schema_version": 1,
        "automatic_updates_enabled": False,
        "schedule_local_time": "02:00",
        "updated_at": None,
        "updated_by": None,
        "error_code": None,
    }
    assert snapshot["update_check"] is None


def test_administrator_can_persist_policy_and_change_is_audited(tmp_path: Path) -> None:
    api, store, repository = client(tmp_path)

    response = api.put(
        "/api/v1/system/version/update/policy",
        headers=headers("admin"),
        json={"automatic_updates_enabled": True},
    )

    assert response.status_code == 200
    policy = response.json()
    assert policy["automatic_updates_enabled"] is True
    assert policy["schedule_local_time"] == "02:00"
    assert policy["updated_by"] == "admin"
    persisted = json.loads((store.root / "update-policy.json").read_text(encoding="utf-8"))
    assert persisted == policy
    audit = repository.list_audit_events(organization_id=ORGANIZATION_ID, limit=10)
    assert audit[0].action == "project_version.update_policy.set"
    assert audit[0].before_snapshot["automatic_updates_enabled"] is False
    assert audit[0].after_snapshot["automatic_updates_enabled"] is True


def test_policy_audit_failure_never_persists_new_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, store, repository = client(tmp_path)
    monkeypatch.setattr(
        repository,
        "append_audit_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        api.put(
            "/api/v1/system/version/update/policy",
            headers=headers("admin"),
            json={"automatic_updates_enabled": True},
        )

    assert not (store.root / "update-policy.json").exists()


def test_manual_check_can_be_queued_while_automatic_updates_are_off(tmp_path: Path) -> None:
    api, store, repository = client(tmp_path)

    response = api.post(
        "/api/v1/system/version/update/checks",
        headers=headers("admin"),
        json={"reason": "operator requested discovery"},
    )

    assert response.status_code == 202
    check = response.json()
    assert check["source"] == "manual"
    assert check["status"] == "queued"
    assert check["actor_subject"] == "admin"
    assert check["reason"] == "operator requested discovery"
    request_path = store.root / "update-check-requests" / f"{check['id']}.json"
    assert request_path.is_file()
    snapshot = api.get("/api/v1/system/version", headers=headers("admin")).json()
    assert snapshot["update_policy"]["automatic_updates_enabled"] is False
    audit = repository.list_audit_events(organization_id=ORGANIZATION_ID, limit=10)
    assert audit[0].action == "project_version.update_check.requested"


def test_check_audit_failure_never_publishes_host_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api, store, repository = client(tmp_path)
    monkeypatch.setattr(
        repository,
        "append_audit_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        api.post(
            "/api/v1/system/version/update/checks",
            headers=headers("admin"),
            json={},
        )

    assert list((store.root / "update-check-requests").glob("*.json")) == []


def test_duplicate_manual_check_fails_closed(tmp_path: Path) -> None:
    api, _, _ = client(tmp_path)
    first = api.post(
        "/api/v1/system/version/update/checks",
        headers=headers("admin"),
        json={},
    )
    assert first.status_code == 202

    second = api.post(
        "/api/v1/system/version/update/checks",
        headers=headers("admin"),
        json={},
    )

    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "update_check_in_progress"


def test_non_administrator_cannot_mutate_policy_or_queue_check(tmp_path: Path) -> None:
    api, store, _ = client(tmp_path)

    policy = api.put(
        "/api/v1/system/version/update/policy",
        headers=headers("engineer"),
        json={"automatic_updates_enabled": True},
    )
    check = api.post(
        "/api/v1/system/version/update/checks",
        headers=headers("engineer"),
        json={},
    )

    assert policy.status_code == 403
    assert check.status_code == 403
    assert not (store.root / "update-policy.json").exists()
    assert list((store.root / "update-check-requests").glob("*.json")) == []


def test_invalid_host_policy_fails_closed_to_off(tmp_path: Path) -> None:
    api, store, _ = client(tmp_path)
    store.root.mkdir(parents=True)
    (store.root / "update-policy.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "automatic_updates_enabled": True,
                "schedule_local_time": "03:00",
            }
        ),
        encoding="utf-8",
    )

    snapshot = api.get("/api/v1/system/version", headers=headers("admin")).json()

    assert snapshot["update_policy"]["automatic_updates_enabled"] is False
    assert snapshot["update_policy"]["error_code"] == "invalid_update_policy"
