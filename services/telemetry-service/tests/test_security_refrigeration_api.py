from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.db import Database
from app.refrigeration.api import create_refrigeration_router
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.storage import InMemoryObjectStorage
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"
ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ORGANIZATION_ID = "22222222-2222-2222-2222-222222222222"


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), (20, 30, 40)).save(output, format="PNG")
    return output.getvalue()


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def build_client(
    tmp_path: Path,
    *,
    subject: str,
    roles: set[Role],
) -> tuple[TestClient, SecurityRepository]:
    database = Database(f"sqlite:///{tmp_path / f'{subject}.db'}")
    database.create_schema()
    security_repository = SecurityRepository(database)
    security_repository.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    security_repository.provision_organization(
        organization_id=OTHER_ORGANIZATION_ID,
        slug="other-lab",
        name="Other Laboratory",
    )
    security_repository.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles,
    )
    dependencies = SecurityDependencies(
        security_repository,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider="test-oidc",
        ),
        default_organization_id=ORGANIZATION_ID,
    )
    app = FastAPI()
    app.include_router(
        create_refrigeration_router(
            PostgresRefrigerationLayoutRepository(database),
            InMemoryObjectStorage(),
            image_max_bytes=15 * 1024 * 1024,
            signed_url_seconds=900,
            security_dependencies=dependencies,
            security_repository=security_repository,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), security_repository


def headers(subject: str, organization_id: str = ORGANIZATION_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": organization_id,
    }


def test_viewer_can_read_but_cannot_edit_layout(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="viewer", roles={Role.VIEWER})

    draft = api.get(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers=headers("viewer"),
    )
    assert draft.status_code == 200

    denied = api.put(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers={**headers("viewer"), "If-Match": draft.headers["etag"]},
        json={"image_id": None, "placements": []},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def test_operator_can_edit_but_cannot_publish(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="operator", roles={Role.OPERATOR})
    draft = api.get(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers=headers("operator"),
    )
    image = api.post(
        "/api/v1/equipment/showcase-1/images",
        headers={**headers("operator"), "X-Actor-Id": "spoofed-user"},
        files={"file": ("showcase.png", png_bytes(), "image/png")},
    )
    assert image.status_code == 201
    assert image.json()["created_by"] == "operator"

    saved = api.put(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers={**headers("operator"), "If-Match": draft.headers["etag"]},
        json={
            "image_id": image.json()["id"],
            "placements": [{"sensor_id": "sensor-1", "x": 0.25, "y": 0.5}],
        },
    )
    assert saved.status_code == 200

    denied = api.post(
        "/api/v1/equipment/showcase-1/layout/publish",
        headers={**headers("operator"), "If-Match": saved.headers["etag"]},
        json={"actor_id": "spoofed-user"},
    )
    assert denied.status_code == 403


def test_engineer_mutations_use_verified_actor_and_write_audit(tmp_path: Path) -> None:
    api, security_repository = build_client(
        tmp_path,
        subject="engineer",
        roles={Role.ENGINEER},
    )
    draft = api.get(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers=headers("engineer"),
    )
    image = api.post(
        "/api/v1/equipment/showcase-1/images",
        headers={**headers("engineer"), "X-Actor-Id": "spoofed-user"},
        files={"file": ("showcase.png", png_bytes(), "image/png")},
    )
    saved = api.put(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers={
            **headers("engineer"),
            "If-Match": draft.headers["etag"],
            "X-Audit-Reason": "Position sensors for acceptance",
        },
        json={
            "image_id": image.json()["id"],
            "placements": [{"sensor_id": "sensor-1", "x": 0.25, "y": 0.5}],
        },
    )
    published = api.post(
        "/api/v1/equipment/showcase-1/layout/publish",
        headers={**headers("engineer"), "If-Match": saved.headers["etag"]},
        json={"actor_id": "spoofed-user"},
    )

    assert published.status_code == 201
    assert published.json()["published"]["published_by"] == "engineer"
    events = security_repository.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="equipment_layout",
        entity_id="showcase-1",
        limit=10,
    )
    assert [event.action for event in events] == [
        "layout.published",
        "layout.draft.updated",
    ]
    assert all(event.actor_subject == "engineer" for event in events)
    assert events[1].reason == "Position sensors for acceptance"


def test_cross_organization_layout_is_not_visible(tmp_path: Path) -> None:
    api, _ = build_client(tmp_path, subject="admin", roles={Role.ADMINISTRATOR})

    denied = api.get(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers=headers("admin", OTHER_ORGANIZATION_ID),
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "organization_membership_not_found"
