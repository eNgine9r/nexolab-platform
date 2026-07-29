from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.repository import (
    LayoutEquipmentRetiredError,
    PostgresRefrigerationLayoutRepository,
)
from app.refrigeration.schemas import RefrigerationEquipmentCreate


def test_soft_deleted_equipment_layout_remains_readable_and_read_only(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'layout-soft-delete.db'}")
    database.create_schema()
    equipment_repository = PostgresRefrigerationEquipmentRepository(database)
    layout_repository = PostgresRefrigerationLayoutRepository(database)

    equipment = equipment_repository.create(
        RefrigerationEquipmentCreate(
            code="CS-SOFT-DELETE-01",
            name="Вітрина soft-delete",
            location="Лабораторія 1 · Зона A",
            laboratory="Лабораторія 1",
            zone="Зона A",
            node_id="kk2",
            equipment_type="Холодильна вітрина",
            manufacturer="NEXOLAB",
            model="NX-SOFT-DELETE",
            serial_number="NX-SOFT-DELETE-0001",
            temperature_class="3M1 (0…+5 °C)",
            installed_at=None,
            serviced_at=None,
            lifecycle_status="active",
            total_sensors=48,
        ),
        actor_id="test-suite",
    )
    original = layout_repository.get_or_create_draft(equipment.id)

    equipment_repository.soft_delete(
        equipment.id,
        expected_version=equipment.version,
        actor_id="test-suite",
    )

    preserved = layout_repository.get_or_create_draft(equipment.id)
    assert preserved.id == original.id
    assert preserved.version == original.version
    assert preserved.placements == []

    with pytest.raises(LayoutEquipmentRetiredError, match="read-only"):
        layout_repository.save_draft(
            equipment_id=equipment.id,
            expected_version=preserved.version,
            image_id=None,
            placements=[],
        )
