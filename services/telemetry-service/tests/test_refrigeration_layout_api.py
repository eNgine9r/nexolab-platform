from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.db import Database
from app.refrigeration.api import create_refrigeration_router
from app.refrigeration.repository import PostgresRefrigerationLayoutRepository
from app.refrigeration.storage import InMemoryObjectStorage


def client(tmp_path: Path) -> tuple[TestClient, PostgresRefrigerationLayoutRepository, InMemoryObjectStorage]:
    database = Database(f"sqlite:///{tmp_path / 'api.db'}")
    database.create_schema()
    repository = PostgresRefrigerationLayoutRepository(database)
    storage = InMemoryObjectStorage()
    app = FastAPI()
    app.include_router(
        create_refrigeration_router(
            repository,
            storage,
            image_max_bytes=15 * 1024 * 1024,
            signed_url_seconds=900,
        )
    )
    return TestClient(app), repository, storage


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), (20, 30, 40)).save(output, format="PNG")
    return output.getvalue()


def test_full_draft_publish_history_restore_flow(tmp_path: Path) -> None:
    api, repository, _ = client(tmp_path)

    draft = api.get("/api/v1/equipment/showcase-1/layout/draft")
    assert draft.status_code == 200
    assert draft.json()["version"] == 1
    assert draft.headers["etag"] == 'W/"layout-draft-v1"'

    image = api.post(
        "/api/v1/equipment/showcase-1/images",
        headers={"X-Actor-Id": "operator-1"},
        files={"file": ("showcase.png", png_bytes(), "image/png")},
    )
    assert image.status_code == 201
    image_payload = image.json()
    assert image_payload["width_px"] == 4
    assert image_payload["height_px"] == 3
    assert image_payload["content_url"].startswith("memory://")

    saved = api.put(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers={"If-Match": draft.headers["etag"]},
        json={
            "image_id": image_payload["id"],
            "placements": [{"sensor_id": "sensor-1", "x": 0.25, "y": 0.5}],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 2

    external = repository.save_draft(
        equipment_id="showcase-1",
        expected_version=2,
        image_id=image_payload["id"],
        placements=saved.json()["placements"],
    )
    assert external.version == 3

    stale = api.put(
        "/api/v1/equipment/showcase-1/layout/draft",
        headers={"If-Match": saved.headers["etag"]},
        json={
            "image_id": image_payload["id"],
            "placements": [{"sensor_id": "sensor-1", "x": 0.9, "y": 0.5}],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "layout_version_conflict",
        "message": "layout version conflict: expected 2, actual 3",
        "expected_version": 2,
        "actual_version": 3,
    }
    assert repository.get_draft("showcase-1").placements[0]["x"] == 0.25

    published = api.post(
        "/api/v1/equipment/showcase-1/layout/publish",
        headers={"If-Match": 'W/"layout-draft-v3"'},
        json={"actor_id": "operator-1"},
    )
    assert published.status_code == 201
    assert published.json()["published"]["revision"] == 1
    assert published.json()["draft"]["version"] == 4

    history = api.get("/api/v1/equipment/showcase-1/layout/history")
    assert history.status_code == 200
    assert [item["revision"] for item in history.json()["items"]] == [1]

    restored = api.post(
        f"/api/v1/equipment/showcase-1/layout/history/{history.json()['items'][0]['id']}/restore",
        headers={"If-Match": 'W/"layout-draft-v4"'},
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 5


def test_upload_rejects_mismatched_media_type(tmp_path: Path) -> None:
    api, _, storage = client(tmp_path)
    response = api.post(
        "/api/v1/equipment/showcase-1/images",
        headers={"X-Actor-Id": "operator-1"},
        files={"file": ("showcase.jpg", png_bytes(), "image/jpeg")},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "image_media_type_mismatch"
    assert storage.objects == {}
