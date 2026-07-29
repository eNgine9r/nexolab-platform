from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.models import CentralNode
from app.refrigeration.equipment_repository import PostgresRefrigerationEquipmentRepository
from app.refrigeration.repository import (
    LayoutEquipmentRetiredError,
    PostgresRefrigerationLayoutRepository,
)
from app.refrigeration.schemas import RefrigerationEquipmentCreate


def test_soft_deleted_equipment_layout_remains_readable_and_read_only(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'layout-soft-delete.db'}")
    database.create_schema()
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                CentralNode(
                    id=str(uuid4()),
                    organization_id="00000000-0000-0000-0000-000000000001",
                    node_id="kk2",
                    display_name="Кліматична камера КК2",
                    state="active",
                    state_reason="test fixture",
                    clock_warning_ms=30_000,
                    clock_critical_ms=120_000,
                    clock_status="ok",
                    created_by="test-suite",
                    created_at=now,
                    updated_at=now,
                )
            )
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
