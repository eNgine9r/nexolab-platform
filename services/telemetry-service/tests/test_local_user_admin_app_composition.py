from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def write_key_pair(directory: Path) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = directory / "local-auth-private.pem"
    public_path = directory / "local-auth-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_create_app_mounts_local_user_admin_routes_when_local_auth_is_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_path, public_path = write_key_pair(tmp_path)
    monkeypatch.setenv("AUTH_LOCAL_ENABLED", "true")
    monkeypatch.setenv("AUTH_LOCAL_PRIVATE_KEY_FILE", str(private_path))
    monkeypatch.setenv("AUTH_LOCAL_PUBLIC_KEY_FILE", str(public_path))
    monkeypatch.setenv("AUTH_LOCAL_ISSUER", "urn:nexolab:test-local")
    monkeypatch.setenv("AUTH_LOCAL_AUDIENCE", "nexolab-test-api")
    monkeypatch.setenv("AUTH_LOCAL_PROVIDER", "nexolab-local")

    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'local-app.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
            auth_mode="jwt",
            auth_default_organization_id="11111111-1111-1111-1111-111111111111",
        )
    )

    with TestClient(app) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]

    assert "/api/v1/auth/local/login" in paths
    assert "/api/v1/admin/users" in paths
    assert "/api/v1/admin/roles" in paths
    assert "/api/v1/admin/permissions" in paths


def test_create_app_does_not_mount_local_admin_routes_without_local_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH_LOCAL_ENABLED", "false")
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'non-local-app.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
            auth_mode="disabled",
        )
    )

    with TestClient(app) as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/admin/users" not in paths
    assert "/api/v1/auth/local/login" not in paths
