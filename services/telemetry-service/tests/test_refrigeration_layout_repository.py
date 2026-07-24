from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.refrigeration.repository import (
    LayoutValidationError,
    LayoutVersionConflictError,
    PostgresRefrigerationLayoutRepository,
)
from app.refrigeration.schemas import SensorPlacementPayload


def repository(tmp_path: Path) -> PostgresRefrigerationLayoutRepository:
    database = Database(f"sqlite:///{tmp_path / 'layouts.db'}")
    database.create_schema()
    return PostgresRefrigerationLayoutRepository(database)


def placement(sensor_id: str = "sensor-1", x: float = 0.2, y: float = 0.3) -> SensorPlacementPayload:
    return SensorPlacementPayload(sensor_id=sensor_id, x=x, y=y)


def add_image(store: PostgresRefrigerationLayoutRepository, equipment_id: str = "equipment-1") -> str:
    image_id = "image-1"
    store.create_image(
        image_id=image_id,
        equipment_id=equipment_id,
        storage_key=f"equipment-images/{image_id}.png",
        original_filename="showcase.png",
        media_type="image/png",
        size_bytes=68,
        width_px=1,
        height_px=1,
        checksum_sha256="a" * 64,
        object_etag='"etag"',
        created_by="operator-1",
    )
    return image_id


def test_save_conflict_does_not_overwrite_current_draft(tmp_path: Path) -> None:
    store = repository(tmp_path)
    draft = store.get_or_create_draft("equipment-1")
    image_id = add_image(store)

    saved = store.save_draft(
        equipment_id="equipment-1",
        expected_version=draft.version,
        image_id=image_id,
        placements=[placement(x=0.4)],
    )
    assert saved.version == 2

    with pytest.raises(LayoutVersionConflictError) as captured:
        store.save_draft(
            equipment_id="equipment-1",
            expected_version=1,
            image_id=image_id,
            placements=[placement(x=0.9)],
        )
    assert captured.value.actual_version == 2
    assert store.get_draft("equipment-1").placements[0]["x"] == 0.4


def test_publish_history_and_restore_are_versioned(tmp_path: Path) -> None:
    store = repository(tmp_path)
    store.get_or_create_draft("equipment-1")
    image_id = add_image(store)
    saved = store.save_draft(
        equipment_id="equipment-1",
        expected_version=1,
        image_id=image_id,
        placements=[placement()],
    )

    published = store.publish(
        equipment_id="equipment-1",
        expected_version=saved.version,
        actor_id="operator-1",
    )
    assert published.published.revision == 1
    assert published.draft.version == 3
    current = store.get_published("equipment-1")
    assert current is not None
    assert current.id == published.published.id
    assert [item.revision for item in store.list_history("equipment-1")] == [1]

    changed = store.save_draft(
        equipment_id="equipment-1",
        expected_version=3,
        image_id=image_id,
        placements=[placement(x=0.8)],
    )
    restored = store.restore(
        equipment_id="equipment-1",
        revision_id=published.published.id,
        expected_version=changed.version,
    )
    assert restored.version == 5
    assert restored.placements[0]["x"] == 0.2


def test_publish_rejects_missing_image_and_duplicate_sensors(tmp_path: Path) -> None:
    store = repository(tmp_path)
    store.get_or_create_draft("equipment-1")
    with pytest.raises(LayoutValidationError) as missing:
        store.publish(equipment_id="equipment-1", expected_version=1, actor_id="operator")
    assert "placements_required" in missing.value.issues

    image_id = add_image(store)
    with pytest.raises(LayoutValidationError) as duplicate:
        store.save_draft(
            equipment_id="equipment-1",
            expected_version=1,
            image_id=image_id,
            placements=[placement(), placement()],
        )
    assert "duplicate_sensor:sensor-1" in duplicate.value.issues
