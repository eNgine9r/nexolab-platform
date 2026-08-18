from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "nexolab-version-manager.py"
SPEC = importlib.util.spec_from_file_location("nexolab_version_manager_runtime", SCRIPT)
assert SPEC and SPEC.loader
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def health_payload(
    *,
    expected: int = 1,
    active: int = 1,
    workers_healthy: bool = True,
    last_attempt_at: str | None = "2026-08-18T10:00:00+00:00",
) -> dict[str, object]:
    return {
        "status": "ok",
        "acquisition": {
            "scheduler": {
                "expected_bus_workers": expected,
                "active_bus_workers": active,
                "workers_healthy": workers_healthy,
            }
        },
        "latest_values": {
            "last_attempt_at": last_attempt_at,
            "last_success_at": last_attempt_at,
        },
    }


def test_device_agent_facts_require_exact_worker_health() -> None:
    expected, active, workers_healthy, last_attempt = manager._device_agent_facts(
        health_payload()
    )

    assert (expected, active, workers_healthy) == (1, 1, True)
    assert last_attempt == "2026-08-18T10:00:00+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        health_payload(expected=1, active=0, workers_healthy=False),
        health_payload(expected=2, active=1, workers_healthy=False),
        {**health_payload(), "status": "error"},
    ],
)
def test_device_agent_facts_fail_closed_on_unhealthy_runtime(payload: dict[str, object]) -> None:
    with pytest.raises(manager.VersionManagerFailure):
        manager._device_agent_facts(payload)


def test_verify_device_agent_progress_requires_timestamp_advance(monkeypatch: pytest.MonkeyPatch) -> None:
    samples = iter(
        [
            health_payload(last_attempt_at="2026-08-18T10:00:00+00:00"),
            health_payload(last_attempt_at="2026-08-18T10:00:03+00:00"),
        ]
    )
    clock = {"value": 0.0}
    monkeypatch.setattr(manager, "read_local_json", lambda _url: next(samples))
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        manager.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    result = manager.verify_device_agent_progress(observation_seconds=10, poll_seconds=3)

    assert result == {
        "status": "verified",
        "expected_bus_workers": 1,
        "active_bus_workers": 1,
        "workers_healthy": True,
        "baseline_last_attempt_at": "2026-08-18T10:00:00+00:00",
        "advanced_last_attempt_at": "2026-08-18T10:00:03+00:00",
    }


def test_verify_device_agent_progress_fails_when_telemetry_does_not_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"value": 0.0}
    monkeypatch.setattr(
        manager,
        "read_local_json",
        lambda _url: health_payload(last_attempt_at="2026-08-18T10:00:00+00:00"),
    )
    monkeypatch.setattr(manager.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        manager.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + seconds),
    )

    with pytest.raises(manager.VersionManagerFailure, match="telemetry did not advance"):
        manager.verify_device_agent_progress(observation_seconds=5, poll_seconds=2)
