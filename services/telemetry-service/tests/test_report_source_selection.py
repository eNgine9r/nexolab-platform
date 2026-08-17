from __future__ import annotations

from typing import Any

import app.reports.source as source_module


def _install_common_stubs(monkeypatch: Any, captured: dict[str, tuple[str, ...] | None]) -> None:
    monkeypatch.setattr(source_module, "_session_payload", lambda _: {"id": "session-1"})
    monkeypatch.setattr(source_module, "_configuration_payload", lambda _: {"id": "config-1"})
    monkeypatch.setattr(source_module, "_stage_payloads", lambda *_: [])
    monkeypatch.setattr(source_module, "_note_payloads", lambda *_: [])
    monkeypatch.setattr(source_module, "_event_payloads", lambda *_: [])
    monkeypatch.setattr(source_module, "_audit_payloads", lambda *_: [])

    def bindings(*_: Any, selected_binding_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        captured["bindings"] = selected_binding_ids
        rows = [{"id": "binding-1"}, {"id": "binding-2"}]
        if selected_binding_ids is None:
            return rows
        selected = set(selected_binding_ids)
        return [row for row in rows if row["id"] in selected]

    def limits(*_: Any, selected_binding_ids: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        captured["limits"] = selected_binding_ids
        return []

    def telemetry(*_: Any, selected_binding_ids: tuple[str, ...] | None = None) -> list[Any]:
        captured["telemetry"] = selected_binding_ids
        return []

    def alerts(*_: Any, selected_binding_ids: tuple[str, ...] | None = None) -> list[Any]:
        captured["alerts"] = selected_binding_ids
        return []

    monkeypatch.setattr(source_module, "_binding_payloads", bindings)
    monkeypatch.setattr(source_module, "_limit_payloads", limits)
    monkeypatch.setattr(source_module, "_telemetry_rows", telemetry)
    monkeypatch.setattr(source_module, "_alert_rows", alerts)


def test_all_session_mode_preserves_unfiltered_legacy_evidence(monkeypatch: Any) -> None:
    captured: dict[str, tuple[str, ...] | None] = {}
    _install_common_stubs(monkeypatch, captured)

    report = source_module.assemble_report_source(
        object(),
        type("Session", (), {"id": "session-1"})(),
        object(),
        selected_binding_ids=("binding-1", "binding-2"),
        selection_mode="all_session_bindings",
    )

    assert captured == {
        "bindings": None,
        "limits": None,
        "telemetry": None,
        "alerts": None,
    }
    assert report.metadata["telemetry_selection"] == {
        "mode": "all_session_bindings",
        "binding_ids": ["binding-1", "binding-2"],
        "binding_count": 2,
    }


def test_explicit_mode_filters_every_binding_scoped_evidence_source(monkeypatch: Any) -> None:
    captured: dict[str, tuple[str, ...] | None] = {}
    _install_common_stubs(monkeypatch, captured)
    selected = ("binding-2",)

    report = source_module.assemble_report_source(
        object(),
        type("Session", (), {"id": "session-1"})(),
        object(),
        selected_binding_ids=selected,
        selection_mode="explicit",
    )

    assert captured == {
        "bindings": selected,
        "limits": selected,
        "telemetry": selected,
        "alerts": selected,
    }
    assert report.metadata["telemetry_selection"] == {
        "mode": "explicit",
        "binding_ids": ["binding-2"],
        "binding_count": 1,
    }
