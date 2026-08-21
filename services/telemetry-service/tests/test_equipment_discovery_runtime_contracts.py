from __future__ import annotations

from pathlib import Path

from app.equipment_discovery.models import EquipmentDiscoveryObservation


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


def test_discovery_observation_index_metadata_matches_migration() -> None:
    index = next(
        item
        for item in EquipmentDiscoveryObservation.__table__.indexes
        if item.name == "ix_equipment_discovery_observations_candidate_time"
    )

    assert tuple(column.name for column in index.columns) == (
        "organization_id",
        "candidate_id",
        "observed_at",
        "id",
    )


def test_discovery_overview_uses_bounded_asset_page_and_separate_total() -> None:
    api_source = (ROOT / "app/equipment_discovery/api.py").read_text(encoding="utf-8")
    repository_source = (ROOT / "app/equipment_discovery/repository.py").read_text(encoding="utf-8")

    assert "network_asset_total = repository.count_network_assets" in api_source
    assert "network_asset_total=network_asset_total" in api_source
    assert "def count_network_assets(" in repository_source
    assert "limit: int = 100" in repository_source
    assert ".offset(offset)" in repository_source
    assert ".limit(limit)" in repository_source


def test_discovery_result_finalization_honors_persisted_cancellation() -> None:
    repository_source = (ROOT / "app/equipment_discovery/repository.py").read_text(encoding="utf-8")

    assert "if scan.cancel_requested:" in repository_source
    assert 'scan.status = "cancelled"' in repository_source
