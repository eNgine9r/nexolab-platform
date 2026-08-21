from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manual_discovery_scan_keeps_sync_repository_calls_off_event_loop() -> None:
    source = (ROOT / "app/equipment_discovery/api.py").read_text(encoding="utf-8")

    assert "import asyncio" in source
    assert "scan = await asyncio.to_thread(" in source
    assert "repository.start_scan," in source
    assert "await asyncio.to_thread(\n                repository.finish_failed," in source


def test_discovery_observation_history_is_bounded_but_retained_rows_stay_immutable() -> None:
    migration = (
        ROOT
        / "migrations/versions/20260820_0026_add_equipment_discovery_inbox.py"
    ).read_text(encoding="utf-8")

    assert "DISCOVERY_OBSERVATION_RETENTION_PER_CANDIDATE = 2016" in migration
    assert "pg_trigger_depth() > 1" in migration
    assert "AFTER INSERT ON equipment_discovery_observations" in migration
    assert "OFFSET {DISCOVERY_OBSERVATION_RETENTION_PER_CANDIDATE}" in migration
    assert "BEFORE UPDATE OR DELETE ON equipment_discovery_observations" in migration
