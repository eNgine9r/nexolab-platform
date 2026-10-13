from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.energy_export.aggregation import available_steps, iter_rows, materialize_cells
from app.energy_export.schemas import COUNTER, ExportError, ExportOptions, SeriesSelection
from app.energy_export.source import micros, open_staging


BASE = datetime(2026, 7, 23, 9, tzinfo=UTC)


def options(metric="electrical.voltage", unit="V", step=60, duration=120):
    return ExportOptions(series=[SeriesSelection(node_id="edge-01", equipment_id="LE01MP-200", channel_id="200-test", metric=metric, unit=unit)], from_at=BASE, to_at=BASE + timedelta(seconds=duration), step_seconds=step, statistics=["avg", "min", "max"], format="csv")


def staging(tmp_path: Path, points: list[tuple], selected: ExportOptions, *, minimum=10, maximum=10):
    path = tmp_path / "source.sqlite"
    with open_staging(path) as db:
        db.execute("CREATE TABLE samples (series INTEGER, captured_us INTEGER, event_id TEXT, value REAL, observed_unit TEXT, quality TEXT, source TEXT, anchor INTEGER)")
        db.execute("CREATE INDEX samples_order ON samples(series,captured_us,event_id)")
        for index, point in enumerate(points):
            seconds, value, *rest = point
            quality = rest[0] if rest else "valid"
            at = BASE + timedelta(seconds=seconds)
            db.execute("INSERT INTO samples VALUES (?,?,?,?,?,?,?,?)", (0, micros(at), f"event-{index:06}", value, selected.series[0].unit, quality, "isolated-test", int(at < selected.from_at or at >= selected.to_at)))
    frozen = {"resolutions": [{"minimum_us": minimum * 1_000_000 if minimum is not None else None, "maximum_us": maximum * 1_000_000 if maximum is not None else None}]}
    return path, frozen


def materialized(tmp_path, points, selected, **kwargs):
    path, frozen = staging(tmp_path, points, selected, **kwargs)
    preview = materialize_cells(path, selected, frozen, guard=lambda: None, progress=lambda _: None)
    return preview, [cells[0] for _, cells in iter_rows(path)]


def test_native_statistics_missing_invalid_and_clipped_buckets(tmp_path):
    selected = options(duration=125)
    preview, cells = materialized(tmp_path, [(0, 220), (10, 240), (20, None, "sensor_error"), (60, None, "sensor_error")], selected)
    assert preview["output_rows"] == 3
    assert (cells[0]["avg"], cells[0]["min"], cells[0]["max"]) == (230, 220, 240)
    assert (cells[0]["source_count"], cells[0]["valid_count"], cells[0]["invalid_count"]) == (3, 2, 1)
    assert cells[0]["status"] == "partial"
    assert cells[1]["avg"] is None and cells[1]["status"] == "invalid"
    assert cells[2]["avg"] is None and cells[2]["status"] == "missing"


def test_counter_shared_actual_anchors_and_no_counter_average(tmp_path):
    selected = options(COUNTER, "kWh")
    points = [(second, 100 + second / 10) for second in range(0, 121, 10)]
    preview, cells = materialized(tmp_path, points, selected)
    assert preview["output_rows"] == 2
    assert [cell["delta_kwh"] for cell in cells] == [6, 6]
    assert [cell["value"] for cell in cells] == [106, 112]
    assert cells[0]["anchor_end_utc"] == cells[1]["anchor_start_utc"]
    assert cells[0]["avg"] is None
    assert cells[1]["source_count"] == 6  # The exact-to reading is only an anchor.


@pytest.mark.parametrize("points,reason", [
    ([(0, 100), (10, 102), (20, 1), (30, 105), (60, 106)], "counter_decrease"),
    ([(0, 100), (10, 101), (20, None, "sensor_error"), (30, 103), (60, 106)], "invalid_counter"),
    ([(0, 100), (10, 101), (60, 106)], "source_gap"),
    ([(0, 100), (0, 101), (10, 102), (60, 107)], "ambiguous_counter_timestamp"),
    ([(0, -5), (10, -2), (60, 1)], "invalid_counter"),
])
def test_counter_detects_interior_discontinuity_even_if_final_reading_is_higher(tmp_path, points, reason):
    _, cells = materialized(tmp_path, points, options(COUNTER, "kWh", duration=60))
    assert cells[0]["delta_kwh"] is None
    assert reason in cells[0]["delta_status"]


def test_raw_same_timestamp_events_are_not_lost_or_averaged(tmp_path):
    preview, cells = materialized(tmp_path, [(0, 220), (0, 221), (30, None, "sensor_error")], options(step=0))
    assert preview["output_rows"] == 3
    assert [cell["value"] for cell in cells] == [220, 221, None]
    assert cells[-1]["status"] == "invalid"


def test_resolution_is_conservative_across_all_selected_series(tmp_path):
    assert available_steps({"resolutions": [{"maximum_us": 10_000_000}, {"maximum_us": 60_000_000}]}) == [0, 60, 300, 600, 900, 1800, 3600]
    assert available_steps({"resolutions": [{"maximum_us": None}]}) == [0]
    path, frozen = staging(tmp_path, [(0, 220), (60, 230)], options(step=10), maximum=60)
    with pytest.raises(ExportError, match="роздільність"):
        materialize_cells(path, options(step=10), frozen, guard=lambda: None, progress=lambda _: None)
