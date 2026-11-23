from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic

from app.config import Settings
from app.db import Database, RetentionResult
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.retention")


class RetentionWorker:
    """Bounded, restart-safe retention (#1551).

    Each cycle runs short batches, one transaction each, until no eligible work
    is left, ``max_batches_per_cycle`` is reached or ``cycle_budget_seconds`` is
    spent, pausing ``batch_pause_seconds`` between batches so ingestion keeps
    priority. A cycle that stops with work left is followed after
    ``backlog_interval_seconds`` instead of the normal interval, which drains a
    large backlog without long transactions. Nothing is kept in memory between
    cycles, so a restart simply resumes from the database state.
    """

    def __init__(
        self,
        *,
        database: Database,
        state: RuntimeState,
        interval_seconds: int,
        batch_size: int,
        telemetry_retention_days: int,
        raw_payload_retention_days: int,
        dead_letter_retention_days: int,
        telemetry_delete_enabled: bool = True,
        max_batches_per_cycle: int = 1,
        cycle_budget_seconds: float = 60.0,
        batch_pause_seconds: float = 0.0,
        backlog_interval_seconds: int | None = None,
    ) -> None:
        self._database = database
        self._state = state
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._telemetry_retention_days = telemetry_retention_days
        self._raw_payload_retention_days = raw_payload_retention_days
        self._dead_letter_retention_days = dead_letter_retention_days
        self._telemetry_delete_enabled = telemetry_delete_enabled
        self._max_batches_per_cycle = max(1, max_batches_per_cycle)
        self._cycle_budget_seconds = cycle_budget_seconds
        self._batch_pause_seconds = batch_pause_seconds
        self._backlog_interval_seconds = backlog_interval_seconds or interval_seconds
        self._stop = Event()
        self._worker = Thread(
            target=self._run,
            name="telemetry-retention",
            daemon=True,
        )

    def start(self) -> None:
        if not self._worker.is_alive():
            self._worker.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._worker.join(timeout=timeout)

    def _batch(self, now: datetime) -> RetentionResult:
        return self._database.cleanup_retention(
            now=now,
            telemetry_retention_days=self._telemetry_retention_days,
            raw_payload_retention_days=self._raw_payload_retention_days,
            dead_letter_retention_days=self._dead_letter_retention_days,
            batch_size=self._batch_size,
            delete_telemetry=self._telemetry_delete_enabled,
        )

    def run_once(self, now: datetime | None = None) -> RetentionResult:
        """Run one cycle of up to ``max_batches_per_cycle`` bounded batches."""
        started = monotonic()
        cutoff_now = now or datetime.now(UTC)
        deleted = redacted = dead_letters = batches = 0
        backlog = False
        try:
            while True:
                result = self._batch(cutoff_now)
                batches += 1
                deleted += result.telemetry_deleted
                redacted += result.raw_payloads_redacted
                dead_letters += result.dead_letters_deleted
                work_left = self._batch_size in (
                    result.telemetry_deleted,
                    result.raw_payloads_redacted,
                    result.dead_letters_deleted,
                )
                if not work_left:
                    break
                if (
                    batches >= self._max_batches_per_cycle
                    or monotonic() - started >= self._cycle_budget_seconds
                ):
                    backlog = True
                    break
                if self._batch_pause_seconds and self._stop.wait(self._batch_pause_seconds):
                    backlog = True
                    break
            duration = round(monotonic() - started, 3)
            cycle = RetentionResult(
                telemetry_deleted=deleted,
                raw_payloads_redacted=redacted,
                dead_letters_deleted=dead_letters,
                batches=batches,
                backlog_remaining=backlog,
                duration_seconds=duration,
            )
            self._state.mark_database_success()
            self._state.mark_retention(
                telemetry_deleted=deleted,
                raw_payloads_redacted=redacted,
                dead_letters_deleted=dead_letters,
                batches=batches,
                duration_seconds=duration,
                backlog_remaining=backlog,
                telemetry_delete_enabled=self._telemetry_delete_enabled,
            )
            LOGGER.info(
                "Retention cycle: telemetry_deleted=%d raw_payloads_redacted=%d "
                "dead_letters_deleted=%d batches=%d duration_seconds=%.3f "
                "backlog_remaining=%s telemetry_delete_enabled=%s",
                deleted,
                redacted,
                dead_letters,
                batches,
                duration,
                backlog,
                self._telemetry_delete_enabled,
            )
            return cycle
        except Exception as exc:
            self._state.increment("retention_failure_total")
            self._state.mark_database_failure(f"retention cleanup failed: {exc}")
            LOGGER.exception("Retention cleanup failed")
            raise

    def next_delay(self, last: RetentionResult | None) -> int:
        if last is not None and last.backlog_remaining:
            return self._backlog_interval_seconds
        return self._interval_seconds

    def _run(self) -> None:
        last: RetentionResult | None = None
        while not self._stop.wait(self.next_delay(last)):
            try:
                last = self.run_once()
            except Exception:  # noqa: BLE001 - background worker boundary
                last = None
                continue


def worker_from_settings(database: Database, state: RuntimeState, settings: Settings) -> RetentionWorker:
    return RetentionWorker(
        database=database,
        state=state,
        interval_seconds=settings.retention_interval_seconds,
        batch_size=settings.retention_batch_size,
        telemetry_retention_days=settings.telemetry_retention_days,
        raw_payload_retention_days=settings.raw_payload_retention_days,
        dead_letter_retention_days=settings.dead_letter_retention_days,
        telemetry_delete_enabled=settings.retention_telemetry_delete_enabled,
        max_batches_per_cycle=settings.retention_max_batches_per_cycle,
        cycle_budget_seconds=settings.retention_cycle_budget_seconds,
        batch_pause_seconds=settings.retention_batch_pause_seconds,
        backlog_interval_seconds=settings.retention_backlog_interval_seconds,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="NEXOLAB telemetry retention")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only count eligible and preserved samples; change nothing",
    )
    args = parser.parse_args(argv)
    settings = Settings()
    database = Database(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        if args.dry_run:
            inventory = database.retention_inventory(
                now=datetime.now(UTC),
                telemetry_retention_days=settings.telemetry_retention_days,
            )
            print(
                json.dumps(
                    {
                        **asdict(inventory),
                        "telemetry_retention_days": settings.telemetry_retention_days,
                        "telemetry_delete_enabled": settings.retention_telemetry_delete_enabled,
                    },
                    sort_keys=True,
                )
            )
            return
        result = worker_from_settings(database, RuntimeState(), settings).run_once()
        print(json.dumps(asdict(result), sort_keys=True))
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
