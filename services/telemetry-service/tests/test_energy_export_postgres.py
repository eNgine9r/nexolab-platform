from __future__ import annotations

import csv
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, func

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryLatest, TelemetrySample
from app.energy_export.aggregation import materialize_cells
from app.energy_export.schemas import CatalogSeries, ExportOptions, SeriesSelection
from app.energy_export.source import freeze_source
from app.energy_export.writer import write_artifact


@pytest.mark.integration
def test_postgresql_frozen_keyset_export_excludes_late_events_without_holding_ingestion_lock(tmp_path):
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("An isolated PostgreSQL integration database is required")
    database = Database(url)
    node = f"energy-export-pg-{uuid4().hex[:12]}"
    base = datetime.now(UTC) - timedelta(hours=2)
    series = SeriesSelection(node_id=node, equipment_id="LE01MP-200", channel_id="200-voltage", metric="electrical.voltage", unit="V")
    options = ExportOptions(series=[series], from_at=base, to_at=base + timedelta(seconds=2000), format="csv")
    expected = {str(uuid4()): 220 + index / 100 for index in range(1101)}
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        with database.engine.begin() as connection:
            connection.execute(insert(TelemetrySample), [{**series.model_dump(), "event_id": event_id, "captured_at": base + timedelta(seconds=index), "value": value, "quality": "valid", "source": "isolated-energy-export-pg-fixture", "raw_payload": {}} for index, (event_id, value) in enumerate(expected.items())])
        late = TelemetryEvent(event_id=uuid4(), **series.model_dump(), captured_at=base + timedelta(seconds=42), value=999, quality="valid", source="isolated-late-pg-fixture")
        inserted = False
        def progress(processed):
            nonlocal inserted
            if processed >= 1000 and not inserted:
                # The normal writer acquires the existing shared ingestion lock.
                # It must finish while the export continues scanning its own snapshot.
                assert executor.submit(database.persist, late, late.normalized_payload()).result(timeout=3)
                inserted = True
        staging = tmp_path / "pg-source.sqlite"
        frozen = freeze_source(database, staging, options, guard=lambda: None, progress=progress)
        assert inserted and frozen["source_events"] == 1101
        assert frozen["source_id_watermark"] > 0
        with database.engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(TelemetrySample).where(TelemetrySample.node_id == node)) == 1102
        prepared = materialize_cells(staging, options, frozen, guard=lambda: None, progress=lambda _: None)
        output = tmp_path / "postgres-original.csv"
        metadata = CatalogSeries(**series.model_dump(), equipment_name="Isolated PostgreSQL fixture", meter_label="W1", parameter_name="Напруга")
        result = write_artifact(staging, output, options, [metadata], {**frozen, **prepared}, guard=lambda: None, progress=lambda _: None)
        with output.open(encoding="utf-8", newline="") as stream:
            actual = {row["U, V · event_id"]: float(row["U, V"]) for row in csv.DictReader(stream)}
        assert result["output_rows"] == 1101 and actual == expected
        assert str(late.event_id) not in actual
    finally:
        executor.shutdown(wait=True)
        # Only this generated fixture node; never broad cleanup or real telemetry.
        with database.engine.begin() as connection:
            connection.execute(delete(TelemetryLatest).where(TelemetryLatest.node_id == node))
            connection.execute(delete(TelemetrySample).where(TelemetrySample.node_id == node))
        database.dispose()
