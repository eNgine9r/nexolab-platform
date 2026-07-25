from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


_SECRET = "nexolab-test-secret-that-is-longer-than-thirty-two-bytes"
_ISSUER = "https://auth.nexolab.test"
_AUDIENCE = "nexolab-api"


def _token(
    *,
    subject: str,
    organization_id: str,
    role: str,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": subject,
        "org_id": organization_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "jti": f"{subject}-{role}",
        "email": f"{subject}@example.com",
        "name": subject.replace("-", " ").title(),
    }
    header = {"alg": "HS256", "typ": "JWT"}

    def section(value: object) -> str:
        encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode()

    encoded_header = section(header)
    encoded_payload = section(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode()
    signature = hmac.new(_SECRET.encode(), signing_input, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def _headers(subject: str, organization_id: str, role: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_token(subject=subject, organization_id=organization_id, role=role)}"
    }


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+pysqlite:///{tmp_path / 'auth.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        auth_mode="jwt",
        auth_jwt_secret=_SECRET,
        auth_jwt_issuer=_ISSUER,
        auth_jwt_audience=_AUDIENCE,
        auth_jwt_leeway_seconds=0,
        auth_auto_provision_memberships=True,
    )
    return TestClient(create_app(settings))


def test_health_is_public_and_api_requires_bearer_token(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/health/live").status_code == 200

        response = client.get("/api/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
    assert response.headers["www-authenticate"] == "Bearer"


def test_session_reports_effective_role_and_permissions(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get(
            "/api/v1/auth/session",
            headers=_headers("viewer-1", "laboratory-a", "viewer"),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["organization_id"] == "laboratory-a"
    assert payload["role"] == "viewer"
    assert "telemetry.read" in payload["permissions"]
    assert "layouts.publish" not in payload["permissions"]


def test_database_membership_role_overrides_later_token_role(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get(
            "/api/v1/auth/session",
            headers=_headers("same-user", "laboratory-a", "viewer"),
        )
        second = client.get(
            "/api/v1/auth/session",
            headers=_headers("same-user", "laboratory-a", "admin"),
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["role"] == "viewer"


def test_viewer_cannot_mutate_layout_but_operator_reaches_endpoint(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        denied = client.post(
            "/api/v1/equipment/cabinet-1/images",
            headers=_headers("viewer-1", "laboratory-a", "viewer"),
        )
        allowed_to_validate = client.post(
            "/api/v1/equipment/cabinet-2/images",
            headers=_headers("operator-1", "laboratory-a", "operator"),
        )

    assert denied.status_code == 403
    assert denied.json()["detail"]["permission"] == "layouts.write"
    assert allowed_to_validate.status_code == 422


def test_operator_cannot_publish_and_admin_can_reach_publish_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        operator = client.post(
            "/api/v1/equipment/cabinet-3/layout/publish",
            headers=_headers("operator-1", "laboratory-a", "operator"),
        )
        admin = client.post(
            "/api/v1/equipment/cabinet-4/layout/publish",
            headers=_headers("admin-1", "laboratory-a", "admin"),
        )

    assert operator.status_code == 403
    assert operator.json()["detail"]["permission"] == "layouts.publish"
    assert admin.status_code == 422


def test_equipment_binding_prevents_cross_organization_access(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        first = client.get(
            "/api/v1/equipment/cabinet-isolated/layout/draft",
            headers=_headers("admin-a", "laboratory-a", "admin"),
        )
        second = client.get(
            "/api/v1/equipment/cabinet-isolated/layout/draft",
            headers=_headers("admin-b", "laboratory-b", "admin"),
        )

    assert first.status_code == 200
    assert second.status_code == 404
    assert second.json()["detail"]["organization_scoped"] is True


def test_denied_and_failed_mutations_are_audited_without_tokens(tmp_path: Path) -> None:
    viewer_headers = _headers("viewer-audit", "laboratory-a", "viewer")
    operator_headers = _headers("operator-audit", "laboratory-a", "operator")
    admin_headers = _headers("admin-audit", "laboratory-a", "admin")

    with _client(tmp_path) as client:
        denied = client.post(
            "/api/v1/equipment/audit-1/images",
            headers=viewer_headers,
        )
        failed = client.post(
            "/api/v1/equipment/audit-2/images",
            headers=operator_headers,
        )
        audit = client.get("/api/v1/audit/events", headers=admin_headers)
        viewer_audit = client.get("/api/v1/audit/events", headers=viewer_headers)

    assert denied.status_code == 403
    assert failed.status_code == 422
    assert audit.status_code == 200
    outcomes = {item["outcome"] for item in audit.json()["items"]}
    assert {"denied", "failed"}.issubset(outcomes)
    assert "Bearer " not in audit.text
    assert _SECRET not in audit.text
    assert viewer_audit.status_code == 403
    assert viewer_audit.json()["detail"]["permission"] == "audit.read"
