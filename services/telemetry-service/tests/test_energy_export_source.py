from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.contracts import TelemetryEvent
from app.energy_export.aggregation import iter_rows, materialize_cells
from app.energy_export.schemas import CatalogSeries, ExportError, ExportOptions, SeriesSelection
from app.energy_export.source import catalog, freeze_source, open_staging, validate_catalog_selection
from app.nodes.models import CentralNode
from tests.live_dashboard_test_support import ORG_A, ORG_B, database_with_inventory


BASE = datetime(2026, 7, 23, 9, tzinfo=UTC)


def source_fixture(tmp_path):
    database, _ = database_with_inventory(tmp_path, filename="energy.db")
    series = SeriesSelection(node_id="edge-a", equipment_id="LE01MP-200", channel_id="200-voltage", metric="electrical.voltage", unit="V")
    for seconds, value in [(0, 220), (0, 221), (30, 230), (60, 240)]:
        sample = TelemetryEvent(event_id=uuid4(), node_id=series.node_id, equipment_id=series.equipment_id, channel_id=series.channel_id, metric=series.metric, unit=series.unit, captured_at=BASE + timedelta(seconds=seconds), value=value, quality="valid", source="isolated-test")
        database.persist(sample, sample.normalized_payload())
    options = ExportOptions(series=[series], from_at=BASE, to_at=BASE + timedelta(seconds=60), format="csv")
    return database, options


def test_source_scope_watermark_boundaries_and_timestamp_collision(tmp_path):
    database, options = source_fixture(tmp_path)
    assert len(catalog(database, ORG_A)) == 1
    assert catalog(database, ORG_B) == []
    assert validate_catalog_selection(database, ORG_A, options)[0].meter_label == "W1"
    with pytest.raises(ExportError, match="організації"):
        validate_catalog_selection(database, ORG_B, options)
    path = tmp_path / "frozen.sqlite"
    frozen = freeze_source(database, path, options, guard=lambda: None, progress=lambda _: None)
    assert frozen["source_events"] == 3
    assert frozen["resolutions"][0]["maximum_us"] == 30_000_000
    preview = materialize_cells(path, options, frozen, guard=lambda: None, progress=lambda _: None)
    assert preview["output_rows"] == 3
    assert sorted(cell["value"] for _, cells in iter_rows(path) for cell in cells.values()) == [220, 221, 230]
    database.dispose()


def test_ambiguous_cross_organization_node_identity_is_not_exported(tmp_path):
    database, _ = source_fixture(tmp_path)
    with Session(database.engine) as session, session.begin():
        session.add(CentralNode(id=str(uuid4()), organization_id=ORG_B, node_id="edge-a", display_name="Foreign duplicate", state="active", created_by="test", clock_status="unknown", clock_warning_ms=30000, clock_critical_ms=120000))
    assert catalog(database, ORG_A) == []
    database.dispose()


def test_retention_loss_during_source_freeze_fails_explicitly(tmp_path):
    database, options = source_fixture(tmp_path)
    from sqlalchemy import delete
    from app.db import TelemetrySample
    changed = False
    def guard():
        nonlocal changed
        if not changed:
            with database.engine.begin() as connection:
                connection.execute(delete(TelemetrySample).where(TelemetrySample.captured_at == BASE))
            changed = True
    with pytest.raises(ExportError, match="Історію змінено"):
        freeze_source(database, tmp_path / "frozen.sqlite", options, guard=guard, progress=lambda _: None)
    database.dispose()


def test_large_delivery_payload_is_not_loaded_by_scalar_history_export(tmp_path):
    from sqlalchemy import event, update
    from app.db import TelemetrySample
    database, options = source_fixture(tmp_path)
    with database.engine.begin() as connection:
        connection.execute(update(TelemetrySample).values(raw_payload={"delivery_metadata": "x" * (256 * 1024)}))
    projections = []
    def observe(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith("select") and "telemetry_samples" in statement.lower():
            projections.append(statement.lower().split("from", 1)[0])
    event.listen(database.engine, "before_cursor_execute", observe)
    try:
        path = tmp_path / "scalar-only.sqlite"
        frozen = freeze_source(database, path, options, guard=lambda: None, progress=lambda _: None)
        assert frozen["source_events"] == 3
        materialize_cells(path, options, frozen, guard=lambda: None, progress=lambda _: None)
        assert sorted(cell["value"] for _, cells in iter_rows(path) for cell in cells.values()) == [220, 221, 230]
        assert projections and all("raw_payload" not in projection for projection in projections)
    finally:
        event.remove(database.engine, "before_cursor_execute", observe)
        database.dispose()


def test_nonexistent_kyiv_time_rejected_and_autumn_offsets_distinct():
    series = SeriesSelection(node_id="edge-a", equipment_id="LE01MP-200", channel_id="v", metric="electrical.voltage", unit="V")
    with pytest.raises(ValidationError, match="Europe/Kyiv"):
        ExportOptions(series=[series], **{"from": "2026-03-29T03:30:00+02:00", "to": "2026-03-29T04:30:00+03:00"})
    first = ExportOptions(series=[series], **{"from": "2026-10-25T03:30:00+03:00", "to": "2026-10-25T04:30:00+02:00"})
    second = ExportOptions(series=[series], **{"from": "2026-10-25T03:30:00+02:00", "to": "2026-10-25T04:30:00+02:00"})
    assert second.from_at - first.from_at == timedelta(hours=1)
