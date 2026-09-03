from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.daily_reports.service import DailyReportSchedulerService


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_daily_report_scheduler_defaults_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAILY_REPORTS_SCHEDULER_ENABLED", raising=False)
    monkeypatch.delenv("DAILY_REPORTS_SCHEDULER_INTERVAL_SECONDS", raising=False)

    settings = Settings()

    assert settings.daily_reports_scheduler_enabled is False
    assert settings.daily_reports_scheduler_interval_seconds == 60


def test_daily_report_scheduler_can_be_explicitly_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAILY_REPORTS_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("DAILY_REPORTS_SCHEDULER_INTERVAL_SECONDS", "120")

    settings = Settings()

    assert settings.daily_reports_scheduler_enabled is True
    assert settings.daily_reports_scheduler_interval_seconds == 120


def test_daily_report_scheduler_interval_remains_bounded() -> None:
    with pytest.raises(ValidationError):
        Settings(daily_reports_scheduler_interval_seconds=9)
    with pytest.raises(ValidationError):
        Settings(daily_reports_scheduler_interval_seconds=3601)


def test_scheduler_service_constructor_is_fail_closed() -> None:
    service = DailyReportSchedulerService(object())  # type: ignore[arg-type]

    assert service.enabled is False
    assert service.start_scheduler() is False
    assert service.running is False


def test_central_compose_defaults_scheduler_off() -> None:
    compose = (REPO_ROOT / "infrastructure/compose/compose.central.yaml").read_text()
    example = (REPO_ROOT / "infrastructure/compose/.env.central.example").read_text()

    assert (
        "DAILY_REPORTS_SCHEDULER_ENABLED: "
        "${DAILY_REPORTS_SCHEDULER_ENABLED:-false}" in compose
    )
    assert (
        "DAILY_REPORTS_SCHEDULER_INTERVAL_SECONDS: "
        "${DAILY_REPORTS_SCHEDULER_INTERVAL_SECONDS:-60}" in compose
    )
    assert "DAILY_REPORTS_SCHEDULER_ENABLED=false" in example
    assert "DAILY_REPORTS_SCHEDULER_INTERVAL_SECONDS=60" in example
