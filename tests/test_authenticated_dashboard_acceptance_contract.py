from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run-authenticated-dashboard-acceptance.sh"


def test_dashboard_history_fixture_keeps_latest_projection_consistent() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    history_insert = "INSERT INTO telemetry_samples ("
    latest_insert = "INSERT INTO telemetry_latest ("

    assert history_insert in script
    assert latest_insert in script
    assert script.index(history_insert) < script.index(latest_insert)
    assert "SELECT DISTINCT ON (" in script
    assert "captured_at DESC," in script
    assert "id DESC" in script
    assert "ON CONFLICT (node_id, equipment_id, channel_id, metric)" in script
    assert "EXCLUDED.captured_at > telemetry_latest.captured_at" in script
    assert "EXCLUDED.sample_id > telemetry_latest.sample_id" in script


def test_dashboard_evidence_captures_history_and_latest_projection() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "FROM telemetry_samples" in script
    assert "FROM telemetry_latest" in script
