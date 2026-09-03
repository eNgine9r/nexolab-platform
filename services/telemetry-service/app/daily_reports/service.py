from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging

from app.daily_reports.domain import latest_due_report_date, resolve_report_window
from app.sessions.time_utils import as_utc
from app.daily_reports.repository import DailyReportRepository
from app.security.authorization import Role

_LOGGER = logging.getLogger(__name__)
_SYSTEM_ACTOR = "system:daily-report-scheduler"


class DailyReportSchedulerService:
    def __init__(
        self,
        repository: DailyReportRepository,
        *,
        enabled: bool = False,
        interval_seconds: int = 60,
    ) -> None:
        self._repository = repository
        self._enabled = enabled
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: datetime | None = None
        self._last_generated_count = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def last_run_at(self) -> datetime | None:
        return self._last_run_at

    @property
    def last_generated_count(self) -> int:
        return self._last_generated_count

    def start_scheduler(self) -> bool:
        if not self._enabled:
            return False
        if self._task is not None and not self._task.done():
            return True
        self._task = asyncio.get_running_loop().create_task(
            self._run_scheduler(),
            name="daily-refrigeration-report-scheduler",
        )
        return True

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def run_due_once(self, now: datetime | None = None) -> int:
        resolved_now = now or datetime.now(UTC)
        if resolved_now.tzinfo is None or resolved_now.utcoffset() is None:
            raise ValueError("scheduler now must be timezone-aware")
        generated = 0
        refs = await asyncio.to_thread(self._repository.list_enabled_profile_refs)
        for organization_id, profile_id in refs:
            scoped = self._repository.for_organization(organization_id)
            try:
                profile = await asyncio.to_thread(scoped.get_profile, profile_id)
                due_date = latest_due_report_date(
                    resolved_now,
                    timezone=profile.timezone,
                    report_hour=profile.report_hour,
                    report_minute=profile.report_minute,
                    weekdays=profile.weekdays,
                )
                if due_date is None:
                    continue
                due_window = resolve_report_window(
                    due_date,
                    timezone=profile.timezone,
                    report_hour=profile.report_hour,
                    report_minute=profile.report_minute,
                    analysis_window_minutes=profile.analysis_window_minutes,
                )
                if due_window.scheduled_for < as_utc(profile.created_at):
                    continue
                result = await asyncio.to_thread(
                    scoped.generate,
                    profile_id,
                    local_report_date=due_date,
                    generated_by=_SYSTEM_ACTOR,
                    actor_identity_id=None,
                    actor_roles=frozenset({Role.ADMINISTRATOR}),
                    reason="Scheduled refrigeration morning report",
                )
                if not result.replayed:
                    generated += 1
            except Exception:
                _LOGGER.exception(
                    "daily refrigeration report generation failed for profile %s",
                    profile_id,
                )
        self._last_run_at = resolved_now.astimezone(UTC)
        self._last_generated_count = generated
        return generated

    async def _run_scheduler(self) -> None:
        # Reconcile the most recent due report immediately after service startup.
        while True:
            try:
                await self.run_due_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("daily refrigeration report scheduler iteration failed")
            await asyncio.sleep(self._interval_seconds)
