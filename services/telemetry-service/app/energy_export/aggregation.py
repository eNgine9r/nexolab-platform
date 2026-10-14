from __future__ import annotations

import json
import math
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Callable, Iterator

from app.energy_export.schemas import COUNTER, ExportError, ExportOptions, iso, normalized_unit
from app.energy_export.source import EPOCH, micros, open_staging


def timestamp(value: int | None) -> str | None:
    return iso(EPOCH + timedelta(microseconds=value)) if value is not None else None


def available_steps(frozen: dict) -> list[int]:
    resolutions = frozen["resolutions"]
    if not resolutions or any(item["maximum_us"] is None for item in resolutions):
        return [0]
    minimum_step_us = max(item["maximum_us"] for item in resolutions)
    return [0, *[value for value in (10, 30, 60, 300, 600, 900, 1800, 3600) if value * 1_000_000 >= minimum_step_us]]


def _valid(row: sqlite3.Row, unit: str) -> bool:
    return row["quality"] == "valid" and normalized_unit(row["observed_unit"]) == normalized_unit(unit) and row["value"] is not None and math.isfinite(row["value"]) and (normalized_unit(unit) != "kwh" or row["value"] >= 0)


def _raw_cell(row: sqlite3.Row, unit: str) -> dict:
    valid = _valid(row, unit)
    return {
        "value": row["value"] if normalized_unit(row["observed_unit"]) == normalized_unit(unit) else None,
        "original_value": row["value"], "observed_unit": row["observed_unit"],
        "quality": row["quality"], "status": "valid" if valid else "invalid",
        "event_id": row["event_id"], "channel_id": None, "source": row["source"],
        "source_count": 1, "valid_count": int(valid), "invalid_count": int(not valid),
        "first_utc": timestamp(row["captured_us"]), "last_utc": timestamp(row["captured_us"]),
    }


def _counter_anchor(connection: sqlite3.Connection, series: int, boundary: int):
    rows = connection.execute("SELECT * FROM samples WHERE series=? AND captured_us<=? ORDER BY captured_us DESC,event_id DESC LIMIT 2", (series, boundary)).fetchall()
    if not rows:
        return None, False
    return rows[0], len(rows) > 1 and rows[0]["captured_us"] == rows[1]["captured_us"]


def _bucket_cell(connection: sqlite3.Connection, series: int, options: ExportOptions, start: int, end: int, resolution: dict, guard: Callable[[], None]) -> dict:
    selected = options.series[series]
    cell = {"value": None, "avg": None, "min": None, "max": None, "quality": "missing", "status": "missing",
            "source_count": 0, "valid_count": 0, "invalid_count": 0, "first_utc": None, "last_utc": None,
            "observed_unit": selected.unit, "source": "", "event_id": "", "original_value": None}
    counter = selected.metric == COUNTER
    start_anchor, ambiguous_start = _counter_anchor(connection, series, start) if counter else (None, False)
    end_anchor, ambiguous_end = _counter_anchor(connection, series, end) if counter else (None, False)
    previous = start_anchor
    continuity = set()
    tolerance = resolution["minimum_us"]
    if counter:
        if ambiguous_start or ambiguous_end:
            continuity.add("ambiguous_counter_timestamp")
        if start_anchor is None or end_anchor is None:
            continuity.add("missing_anchor")
        elif tolerance is None or start - start_anchor["captured_us"] > tolerance or end - end_anchor["captured_us"] > tolerance:
            continuity.add("insufficient_boundary_coverage")
        if start_anchor is not None and not _valid(start_anchor, selected.unit):
            continuity.add("invalid_anchor")

    def check_counter(row):
        nonlocal previous
        if not _valid(row, selected.unit):
            continuity.add("invalid_counter")
        elif previous is not None and row["event_id"] != previous["event_id"]:
            if not _valid(previous, selected.unit):
                continuity.add("invalid_counter")
            else:
                if row["value"] < previous["value"]:
                    continuity.add("counter_decrease")
                gap = row["captured_us"] - previous["captured_us"]
                if gap == 0:
                    continuity.add("ambiguous_counter_timestamp")
                elif tolerance is None or gap > tolerance * 3:
                    continuity.add("source_gap")
        previous = row

    mean = 0.0
    for row in connection.execute("SELECT * FROM samples WHERE series=? AND captured_us>=? AND captured_us<? AND anchor=0 ORDER BY captured_us,event_id", (series, start, end)):
        cell["source_count"] += 1
        if cell["source_count"] % 1000 == 0:
            guard()
        cell["first_utc"] = cell["first_utc"] or timestamp(row["captured_us"])
        cell["last_utc"] = timestamp(row["captured_us"])
        if _valid(row, selected.unit):
            cell["valid_count"] += 1
            value = row["value"]
            count = cell["valid_count"]
            mean = mean * (1 - 1 / count) + value / count
            cell["min"] = value if cell["min"] is None else min(cell["min"], value)
            cell["max"] = value if cell["max"] is None else max(cell["max"], value)
        else:
            cell["invalid_count"] += 1
        if counter:
            check_counter(row)
    if cell["valid_count"]:
        cell["avg"] = mean if math.isfinite(mean) else None
        cell["value"] = cell["avg"]
        cell["quality"] = cell["status"] = "partial" if cell["invalid_count"] else "valid"
    elif cell["source_count"]:
        cell["quality"] = cell["status"] = "invalid"
    if counter:
        if end_anchor is not None and (previous is None or end_anchor["event_id"] != previous["event_id"]):
            check_counter(end_anchor)
        reasons = sorted(set(continuity))
        cell.update({"avg": None, "min": None, "max": None,
                     "value": end_anchor["value"] if end_anchor is not None and _valid(end_anchor, selected.unit) else None,
                     "delta_kwh": None, "delta_status": ";".join(reasons) if reasons else "boundary_tolerance",
                     "anchor_start_utc": timestamp(start_anchor["captured_us"]) if start_anchor is not None else None,
                     "anchor_end_utc": timestamp(end_anchor["captured_us"]) if end_anchor is not None else None,
                     "anchor_tolerance_seconds": tolerance / 1_000_000 if tolerance is not None else None,
                     "covered_seconds": (end_anchor["captured_us"] - start_anchor["captured_us"]) / 1_000_000 if start_anchor is not None and end_anchor is not None else None})
        if not reasons and start_anchor is not None and end_anchor is not None:
            delta = end_anchor["value"] - start_anchor["value"]
            if math.isfinite(delta) and delta >= 0:
                cell["delta_kwh"] = delta
            else:
                cell["delta_status"] = "invalid_delta"
        if cell["delta_kwh"] is None:
            cell["quality"] = cell["status"] = "incomplete_counter"
    return cell


def materialize_cells(path: Path, options: ExportOptions, frozen: dict, *, guard: Callable[[], None], progress: Callable[[int], None]) -> dict:
    steps = available_steps(frozen)
    if options.step_seconds not in steps:
        raise ExportError("step_unavailable", "Крок менший за підтверджену роздільність збереженої історії або вона невідома. Оберіть RAW чи більший крок.")
    connection = open_staging(path)
    connection.row_factory = sqlite3.Row
    meters = list(dict.fromkeys((item.node_id, item.equipment_id) for item in options.series))
    meter_indices = [meters.index((item.node_id, item.equipment_id)) for item in options.series]
    connection.execute("CREATE TABLE cells (row_us INTEGER NOT NULL, meter INTEGER NOT NULL, collision INTEGER NOT NULL, series INTEGER NOT NULL, payload TEXT NOT NULL)")
    processed = 0
    try:
        if options.step_seconds == 0:
            query = "SELECT *, ROW_NUMBER() OVER (PARTITION BY series,captured_us ORDER BY event_id)-1 AS collision FROM samples WHERE anchor=0 ORDER BY series,captured_us,event_id"
            for row in connection.execute(query):
                cell = _raw_cell(row, options.series[row["series"]].unit)
                connection.execute("INSERT INTO cells VALUES (?,?,?,?,?)", (row["captured_us"], meter_indices[row["series"]], row["collision"], row["series"], json.dumps(cell, ensure_ascii=False, allow_nan=False)))
                processed += 1
                if processed % 1000 == 0:
                    connection.commit(); guard(); progress(processed)
        else:
            first, final = micros(options.from_at), micros(options.to_at)
            step = options.step_seconds * 1_000_000
            for series in range(len(options.series)):
                for start in range(first, final, step):
                    cell = _bucket_cell(connection, series, options, start, min(final, start + step), frozen["resolutions"][series], guard)
                    connection.execute("INSERT INTO cells VALUES (?,?,?,?,?)", (start, meter_indices[series], 0, series, json.dumps(cell, ensure_ascii=False, allow_nan=False)))
                    processed += 1
                    if processed % 1000 == 0:
                        connection.commit(); guard(); progress(processed)
        connection.commit()
        guard()
        connection.execute("CREATE INDEX cells_order ON cells(row_us,meter,collision,series)")
        connection.commit()
        guard()
        rows = connection.execute("SELECT COUNT(*) FROM (SELECT 1 FROM cells GROUP BY row_us,meter,collision)").fetchone()[0]
        return {"output_rows": rows, "available_steps": steps, "estimated_bytes": max(2048, rows * (250 + len(options.series) * 250)),
                "resolution_method": "maximum_observed_adjacent_interval; gaps conservatively restrict steps"}
    finally:
        connection.close()


def iter_rows(path: Path) -> Iterator[tuple[tuple[int, int, int], dict[int, dict]]]:
    connection = open_staging(path)
    try:
        key = None
        cells = {}
        for at, meter, collision, series, payload in connection.execute("SELECT * FROM cells ORDER BY row_us,meter,collision,series"):
            row_key = at, meter, collision
            if key is not None and row_key != key:
                yield key, cells
                cells = {}
            key = row_key
            cells[series] = json.loads(payload)
        if key is not None:
            yield key, cells
    finally:
        connection.close()
