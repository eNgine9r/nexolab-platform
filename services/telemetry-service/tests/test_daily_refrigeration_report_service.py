from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.daily_reports.service import DailyReportSchedulerService


class FakeScopedRepository:
    def __init__(self) -> None:
        self.generated_dates: list[date] = []

    def get_profile(self, profile_id: str):
        assert profile_id == "profile-1"
        return SimpleNamespace(
            timezone="Europe/Kyiv",
            report_hour=7,
            report_minute=50,
            weekdays=[0, 1, 2, 3, 4],
            analysis_window_minutes=720,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

    def generate(self, profile_id: str, *, local_report_date: date, **_kwargs):
        assert profile_id == "profile-1"
        replayed = local_report_date in self.generated_dates
        if not replayed:
            self.generated_dates.append(local_report_date)
        return SimpleNamespace(replayed=replayed)


class FakeRepository:
    def __init__(self) -> None:
        self.scoped = FakeScopedRepository()

    def list_enabled_profile_refs(self):
        return [("organization-1", "profile-1")]

    def for_organization(self, organization_id: str):
        assert organization_id == "organization-1"
        return self.scoped


def test_scheduler_catches_up_latest_due_report_once_across_replays() -> None:
    repository = FakeRepository()
    service = DailyReportSchedulerService(repository)  # type: ignore[arg-type]
    # Monday 07:00 Kyiv: Friday is the latest due weekday.
    now = datetime(2026, 9, 7, 4, 0, tzinfo=UTC)

    first = asyncio.run(service.run_due_once(now))
    second = asyncio.run(service.run_due_once(now))

    assert first == 1
    assert second == 0
    assert repository.scoped.generated_dates == [date(2026, 9, 4)]
    assert service.last_generated_count == 0
    assert service.last_run_at == now


def test_scheduler_does_not_backfill_before_profile_creation() -> None:
    repository = FakeRepository()
    repository.scoped.get_profile = lambda _profile_id: SimpleNamespace(
        timezone="Europe/Kyiv",
        report_hour=7,
        report_minute=50,
        weekdays=[0, 1, 2, 3, 4],
        analysis_window_minutes=720,
        created_at=datetime(2026, 9, 7, 3, 0, tzinfo=UTC),
    )
    service = DailyReportSchedulerService(repository)  # type: ignore[arg-type]

    generated = asyncio.run(
        service.run_due_once(datetime(2026, 9, 7, 4, 0, tzinfo=UTC))
    )

    assert generated == 0
    assert repository.scoped.generated_dates == []
