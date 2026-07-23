from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from threading import Event, Thread

from app.config import Settings
from app.db import Database, RetentionResult
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.retention")


class RetentionWorker:
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
    ) -> None:
        self._database = database
        self._state = state
        self._interval_seconds = interval_seconds
        self._batch_size = batch_size
        self._telemetry_retention_days = telemetry_retention_days
        self._raw_payload_retention_days = raw_payload_retention_days
        self._dead_letter_retention_days = dead_letter_retention_days
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

    def run_once(self, now: datetime | None = None) -> RetentionResult:
        try:
            result = self._database.cleanup_retention(
                now=now or datetime.now(UTC),
                telemetry_retention_days=self._telemetry_retention_days,
                raw_payload_retention_days=self._raw_payload_retention_days,
                dead_letter_retention_days=self._dead_letter_retention_days,
                batch_size=self._batch_size,
            )
            self._state.mark_database_success()
            self._state.mark_retention(
                telemetry_deleted=result.telemetry_deleted,
                raw_payloads_redacted=result.raw_payloads_redacted,
                dead_letters_deleted=result.dead_letters_deleted,
            )
            LOGGER.info(
                "Retention completed: telemetry_deleted=%d "
                "raw_payloads_redacted=%d dead_letters_deleted=%d",
                result.telemetry_deleted,
                result.raw_payloads_redacted,
                result.dead_letters_deleted,
            )
            return result
        except Exception as exc:
            self._state.increment("retention_failure_total")
            self._state.mark_database_failure(f"retention cleanup failed: {exc}")
            LOGGER.exception("Retention cleanup failed")
            raise

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - background worker boundary
                continue


def main() -> None:
    settings = Settings()
    database = Database(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    state = RuntimeState()
    worker = RetentionWorker(
        database=database,
        state=state,
        interval_seconds=settings.retention_interval_seconds,
        batch_size=settings.retention_batch_size,
        telemetry_retention_days=settings.telemetry_retention_days,
        raw_payload_retention_days=settings.raw_payload_retention_days,
        dead_letter_retention_days=settings.dead_letter_retention_days,
    )
    try:
        result = worker.run_once()
        print(json.dumps(result.__dict__, sort_keys=True))
    finally:
        database.dispose()


if __name__ == "__main__":
    main()
