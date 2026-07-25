from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.db import Database
from app.operator_identity import OperatorIdentityResolver
from app.refrigeration.api import create_refrigeration_router
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.storage import InMemoryObjectStorage


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), (20, 30, 40)).save(output, format="PNG")
    return output.getvalue()


def tailscale_client(tmp_path: Path) -> tuple[TestClient, PostgresRefrigerationLayoutRepository]:
    database = Database(f"sqlite:///{tmp_path / 'tailscale-api.db'}")
    database.create_schema()
    repository = PostgresRefrigerationLayoutRepository(database)
    app = FastAPI()
    app.include_router(
        create_refrigeration_router(
            repository,
            InMemoryObjectStorage(),
            image_max_bytes=15 * 1024 * 1024,
            signed_url_seconds=900,
            operator_identity=OperatorIdentityResolver("tailscale_serve"),
        )
    )
    return TestClient(app), repository


def test_tailscale_identity_overrides_spoofed_upload_and_publish_actor(tmp_path: Path) -> None:
    api, repository = tailscale_client(tmp_path)
    identity_headers = {
        "Tailscale-User-Login": "operator@example.com",
        "Tailscale-User-Name": "NEXOLAB Operator",
    }

    draft = api.get("/api/v1/equipment/showcase-identity/layout/draft")
    assert draft.status_code == 200

    image = api.post(
        "/api/v1/equipment/showcase-identity/images",
        headers={**identity_headers, "X-Actor-Id": "spoofed-upload-actor"},
        files={"file": ("showcase.png", png_bytes(), "image/png")},
    )
    assert image.status_code == 201
    assert image.json()["created_by"] == "operator@example.com"

    saved = api.put(
        "/api/v1/equipment/showcase-identity/layout/draft",
        headers={"If-Match": draft.headers["etag"]},
        json={
            "image_id": image.json()["id"],
            "placements": [{"sensor_id": "sensor-1", "x": 0.25, "y": 0.5}],
        },
    )
    assert saved.status_code == 200

    published = api.post(
        "/api/v1/equipment/showcase-identity/layout/publish",
        headers={**identity_headers, "If-Match": saved.headers["etag"]},
        json={"actor_id": "spoofed-publish-actor"},
    )
    assert published.status_code == 201
    assert published.json()["published"]["published_by"] == "operator@example.com"
    assert repository.get_published("showcase-identity").published_by == "operator@example.com"


def test_tailscale_identity_is_required_for_mutations(tmp_path: Path) -> None:
    api, _ = tailscale_client(tmp_path)

    response = api.post(
        "/api/v1/equipment/showcase-identity/images",
        headers={"X-Actor-Id": "browser-actor"},
        files={"file": ("showcase.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "operator_identity_required"
