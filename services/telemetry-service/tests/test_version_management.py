from __future__ import annotations

import json
import hashlib
from datetime import UTC, datetime, timedelta
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
from app.version_management import (
    VersionManagementStore,
    create_version_management_router,
)


SECRET = "version-management-test-secret-with-sufficient-length"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def _token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "iss": "version-tests",
            "aud": "nexolab-api",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def _headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject)}",
        "X-Organization-ID": ORGANIZATION_ID,
    }


def _manifest(
    root: Path,
    bundle_id: str,
    *,
    release: str,
    commit: str,
    schema: str,
    upgrade_from: list[str],
    runtime_compatible: list[str],
    platform: str = "linux/arm64",
) -> None:
    directory = root / "catalog" / bundle_id
    directory.mkdir(parents=True)
    manifest = json.dumps(
            {
                "schema_version": 1,
                "bundle_version": release,
                "source_commit": commit,
                "created_at": "2026-08-13T10:00:00+00:00",
                "platform": platform,
                "persistent_data_policy": {
                    "packaged": False,
                    "delete_volumes": False,
                    "compose_down_v_allowed": False,
                },
                "version_management": {
                    "bundle_id": bundle_id,
                    "database_schema": {
                        "head": schema,
                        "upgrade_from": upgrade_from,
                        "runtime_compatible_schema_heads": runtime_compatible,
                    },
                },
            }
        )
    (directory / "manifest.json").write_text(manifest, encoding="utf-8")
    (directory / ".nexolab-validated.json").write_text(
        json.dumps({"manifest_sha256": hashlib.sha256(manifest.encode()).hexdigest()}),
        encoding="utf-8",
    )


def _current(root: Path) -> None:
    (root / "current.json").write_text(
        json.dumps(
            {
                "bundle_id": "release-1",
                "release": "1.0.0",
                "source_commit": "1" * 40,
                "build_timestamp": "2026-08-12T10:00:00Z",
                "runtime_mode": "lan",
                "platform": "linux/arm64",
                "schema_head": "schema-1",
                "deployed_at": "2026-08-12T10:05:00Z",
                "health": "ready",
                "previous_bundle_id": None,
                "previous_release": None,
                "last_operation_id": None,
            }
        ),
        encoding="utf-8",
    )


def _client(tmp_path: Path) -> tuple[TestClient, VersionManagementStore, SecurityRepository]:
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
            issuer="version-tests",
            audience="nexolab-api",
            provider="test",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    store = VersionManagementStore(tmp_path / "versions")
    app = FastAPI()
    app.include_router(create_version_management_router(store, dependencies, repository))
    return TestClient(app), store, repository


def test_read_model_is_offline_and_rejects_untrusted_manifests(tmp_path: Path) -> None:
    api, store, _ = _client(tmp_path)
    store.root.mkdir()
    _current(store.root)
    _manifest(
        store.root,
        "release-1",
        release="1.0.0",
        commit="1" * 40,
        schema="schema-1",
        upgrade_from=["schema-0"],
        runtime_compatible=["schema-1"],
    )
    rejected = store.root / "catalog" / "unverified"
    rejected.mkdir()
    (rejected / "manifest.json").write_text('{"schema_version":1}', encoding="utf-8")

    response = api.get("/api/v1/system/version", headers=_headers("admin"))

    assert response.status_code == 200
    payload = response.json()
    assert payload["offline"] is True
    assert payload["current"]["known_packaged_release"] is True
    assert [item["bundle_id"] for item in payload["catalog"]] == ["release-1"]
    assert payload["rejected_packages"][0]["code"] == "invalid_package_manifest"


def test_non_administrator_is_forbidden_server_side(tmp_path: Path) -> None:
    api, _, _ = _client(tmp_path)

    response = api.get("/api/v1/system/version", headers=_headers("engineer"))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "permission_denied"


def test_update_is_queued_atomically_and_audited(tmp_path: Path) -> None:
    api, store, repository = _client(tmp_path)
    store.root.mkdir()
    _current(store.root)
    _manifest(
        store.root,
        "release-1",
        release="1.0.0",
        commit="1" * 40,
        schema="schema-1",
        upgrade_from=["schema-0"],
        runtime_compatible=["schema-1", "schema-2"],
    )
    _manifest(
        store.root,
        "release-2",
        release="2.0.0",
        commit="2" * 40,
        schema="schema-2",
        upgrade_from=["schema-1"],
        runtime_compatible=["schema-2"],
    )

    response = api.post(
        "/api/v1/system/version/actions",
        headers=_headers("admin"),
        json={
            "action": "update",
            "target_bundle_id": "release-2",
            "confirmation": "APPLY release-2",
            "reason": "controlled acceptance",
        },
    )

    assert response.status_code == 202
    operation = response.json()
    assert operation["status"] == "queued"
    assert (store.root / "requests" / f"{operation['id']}.json").is_file()
    assert (store.root / "operations" / f"{operation['id']}.json").is_file()
    audit = repository.list_audit_events(organization_id=ORGANIZATION_ID, limit=10)
    assert audit[0].action == "project_version.update.requested"
    assert audit[0].after_snapshot == {
        "bundle_id": "release-2",
        "release": "2.0.0",
        "commit": "2" * 40,
        "status": "queued",
    }


def test_audit_failure_never_publishes_host_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api, store, repository = _client(tmp_path)
    store.root.mkdir()
    _current(store.root)
    _manifest(
        store.root,
        "release-1",
        release="1.0.0",
        commit="1" * 40,
        schema="schema-1",
        upgrade_from=["schema-0"],
        runtime_compatible=["schema-1"],
    )
    _manifest(
        store.root,
        "release-2",
        release="2.0.0",
        commit="2" * 40,
        schema="schema-2",
        upgrade_from=["schema-1"],
        runtime_compatible=["schema-2"],
    )
    monkeypatch.setattr(
        repository,
        "append_audit_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        api.post(
            "/api/v1/system/version/actions",
            headers=_headers("admin"),
            json={
                "action": "update",
                "target_bundle_id": "release-2",
                "confirmation": "APPLY release-2",
            },
        )

    assert list((store.root / "requests").glob("*.json")) == []
    assert list((store.root / "operations").glob("*.json")) == []


def test_unknown_schema_compatibility_hard_stops_without_request(tmp_path: Path) -> None:
    api, store, _ = _client(tmp_path)
    store.root.mkdir()
    _current(store.root)
    _manifest(
        store.root,
        "release-1",
        release="1.0.0",
        commit="1" * 40,
        schema="schema-1",
        upgrade_from=["schema-0"],
        runtime_compatible=["schema-1"],
    )
    _manifest(
        store.root,
        "release-unsafe",
        release="3.0.0",
        commit="3" * 40,
        schema="schema-3",
        upgrade_from=["schema-2"],
        runtime_compatible=["schema-3"],
    )

    response = api.post(
        "/api/v1/system/version/actions",
        headers=_headers("admin"),
        json={
            "action": "update",
            "target_bundle_id": "release-unsafe",
            "confirmation": "APPLY release-unsafe",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "schema_compatibility_unknown"
    assert list((store.root / "requests").glob("*.json")) == []


def test_rollback_is_limited_to_previous_known_good(tmp_path: Path) -> None:
    api, store, _ = _client(tmp_path)
    store.root.mkdir()
    _current(store.root)
    current = json.loads((store.root / "current.json").read_text(encoding="utf-8"))
    current["bundle_id"] = "release-2"
    current["release"] = "2.0.0"
    current["source_commit"] = "2" * 40
    current["schema_head"] = "schema-2"
    current["previous_bundle_id"] = "release-1"
    current["previous_release"] = "1.0.0"
    (store.root / "current.json").write_text(json.dumps(current), encoding="utf-8")
    _manifest(
        store.root,
        "release-2",
        release="2.0.0",
        commit="2" * 40,
        schema="schema-2",
        upgrade_from=["schema-1"],
        runtime_compatible=["schema-2"],
    )
    _manifest(
        store.root,
        "release-1",
        release="1.0.0",
        commit="1" * 40,
        schema="schema-1",
        upgrade_from=["schema-0"],
        runtime_compatible=["schema-1", "schema-2"],
    )

    response = api.post(
        "/api/v1/system/version/actions",
        headers=_headers("admin"),
        json={
            "action": "rollback",
            "target_bundle_id": "release-1",
            "confirmation": "ROLLBACK release-1",
        },
    )

    assert response.status_code == 202
    assert response.json()["action"] == "rollback"
