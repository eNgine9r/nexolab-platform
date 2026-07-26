from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.security.models import (
    SecurityIdentity,
    SecurityMembershipRole,
    SecurityOrganization,
    SecurityOrganizationMembership,
)

ORGANIZATION_A = "aaaaaaaa-1111-4111-8111-111111111111"
ORGANIZATION_B = "bbbbbbbb-2222-4222-8222-222222222222"
JWT_SECRET = "organization-session-api-test-secret"
ISSUER = "https://identity.session-scope.test"
AUDIENCE = "nexolab-api"


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def token(subject: str) -> str:
    now = int(time.time())
    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = encode(
        json.dumps(
            {
                "sub": subject,
                "iss": ISSUER,
                "aud": AUDIENCE,
                "iat": now,
                "exp": now + 600,
            }
        ).encode()
    )
    signature = encode(
        hmac.new(
            JWT_SECRET.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256,
        ).digest()
    )
    return f"{header}.{payload}.{signature}"


def build_client(database_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        auth_mode="jwt",
        auth_jwt_public_key=JWT_SECRET,
        auth_jwt_algorithm="HS256",
        auth_jwt_issuer=ISSUER,
        auth_jwt_audience=AUDIENCE,
        auth_jwt_provider="scope-test-oidc",
    )
    app = create_app(settings)
    with Session(app.state.database.engine) as session:
        organizations = [
            SecurityOrganization(
                id=ORGANIZATION_A,
                slug="scope-a",
                name="Scope A",
            ),
            SecurityOrganization(
                id=ORGANIZATION_B,
                slug="scope-b",
                name="Scope B",
            ),
        ]
        session.add_all(organizations)
        for organization_id, subject, suffix in (
            (ORGANIZATION_A, "engineer-a", "a"),
            (ORGANIZATION_B, "engineer-b", "b"),
        ):
            identity = SecurityIdentity(
                id=f"cccccccc-cccc-4ccc-8ccc-ccccccccccc{suffix}",
                provider="scope-test-oidc",
                subject=subject,
                is_active=True,
            )
            membership = SecurityOrganizationMembership(
                id=f"dddddddd-dddd-4ddd-8ddd-ddddddddddd{suffix}",
                organization_id=organization_id,
                identity_id=identity.id,
                is_active=True,
            )
            session.add_all(
                [
                    identity,
                    membership,
                    SecurityMembershipRole(
                        membership_id=membership.id,
                        role="engineer",
                        assigned_by="scope-test",
                    ),
                ]
            )
        session.commit()
    return TestClient(app)


def headers(subject: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": organization_id,
    }


def create_payload() -> dict[str, object]:
    return {
        "session_number": "NXL-SHARED-API-001",
        "title": "Scoped API session",
        "test_object": "K106",
        "node_id": "edge-01",
        "actor_id": "spoofed-browser-actor",
        "actor_source": "spoofed-browser-source",
    }


def test_session_api_is_scoped_and_actor_is_verified(tmp_path: Path) -> None:
    with build_client(tmp_path / "session-api-scope.db") as client:
        created_a = client.post(
            "/api/v1/sessions",
            headers={
                **headers("engineer-a", ORGANIZATION_A),
                "Idempotency-Key": "same-create-key",
            },
            json=create_payload(),
        )
        created_b = client.post(
            "/api/v1/sessions",
            headers={
                **headers("engineer-b", ORGANIZATION_B),
                "Idempotency-Key": "same-create-key",
            },
            json=create_payload(),
        )
        assert created_a.status_code == 201, created_a.text
        assert created_b.status_code == 201, created_b.text
        body_a = created_a.json()
        body_b = created_b.json()
        assert body_a["session"]["organization_id"] == ORGANIZATION_A
        assert body_b["session"]["organization_id"] == ORGANIZATION_B
        assert body_a["session"]["id"] != body_b["session"]["id"]
        assert body_a["event"]["actor_id"] == "engineer-a"
        assert body_a["event"]["actor_source"] == "scope-test-oidc"

        own_list = client.get(
            "/api/v1/sessions",
            headers=headers("engineer-a", ORGANIZATION_A),
        )
        foreign_get = client.get(
            f"/api/v1/sessions/{body_a['session']['id']}",
            headers=headers("engineer-b", ORGANIZATION_B),
        )
        missing_get = client.get(
            f"/api/v1/sessions/{uuid4()}",
            headers=headers("engineer-b", ORGANIZATION_B),
        )
        foreign_configuration = client.get(
            f"/api/v1/sessions/{body_a['session']['id']}/configuration",
            headers=headers("engineer-b", ORGANIZATION_B),
        )
        foreign_telemetry = client.get(
            f"/api/v1/sessions/{body_a['session']['id']}/telemetry/latest",
            headers=headers("engineer-b", ORGANIZATION_B),
        )

        assert own_list.status_code == 200
        assert [item["id"] for item in own_list.json()["items"]] == [
            body_a["session"]["id"]
        ]
        assert foreign_get.status_code == missing_get.status_code == 404
        assert foreign_get.json()["detail"]["code"] == "session_not_found"
        assert foreign_configuration.status_code == 404
        assert foreign_telemetry.status_code == 404
