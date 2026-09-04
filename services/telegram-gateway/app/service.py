from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from threading import Event, RLock, Thread
from typing import Callable

from app.backend import BackendError, SnapshotClient
from app.config import Settings
from app.outbox import DeliveryOutbox
from app.render import RenderError, render_report
from app.telegram import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    enabled: bool
    running: bool
    last_poll_at: datetime | None
    last_send_at: datetime | None
    last_error_code: str | None
    recovered_unknown_deliveries: int


class GatewayRuntime:
    def __init__(self, *, enabled: bool) -> None:
        self._lock = RLock()
        self._enabled = enabled
        self._running = False
        self._last_poll_at: datetime | None = None
        self._last_send_at: datetime | None = None
        self._last_error_code: str | None = None
        self._recovered_unknown_deliveries = 0
    def set_running(self, value: bool) -> None:
        with self._lock:
            self._running = value

    def record_poll(self, when: datetime) -> None:
        with self._lock:
            self._last_poll_at = when

    def record_send(self, when: datetime) -> None:
        with self._lock:
            self._last_send_at = when
            self._last_error_code = None

    def record_error(self, code: str) -> None:
        with self._lock:
            self._last_error_code = code[:96]

    def record_recovered_unknown(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self._recovered_unknown_deliveries += count

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                enabled=self._enabled,
                running=self._running,
                last_poll_at=self._last_poll_at,
                last_send_at=self._last_send_at,
                last_error_code=self._last_error_code,
                recovered_unknown_deliveries=self._recovered_unknown_deliveries,
            )


class TelegramDeliveryWorker:
    def __init__(
        self,
        settings: Settings,
        snapshot_client: SnapshotClient,
        telegram_client: TelegramClient,
        outbox: DeliveryOutbox,
        runtime: GatewayRuntime,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._snapshot_client = snapshot_client
        self._telegram_client = telegram_client
        self._outbox = outbox
        self._runtime = runtime
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="telegram-delivery-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._runtime.set_running(False)

    def _run(self) -> None:
        self._runtime.set_running(True)
        try:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self._settings.telegram_poll_interval_seconds)
        finally:
            self._runtime.set_running(False)

    def run_once(self) -> None:
        now = _aware_utc(self._clock())
        recovered = self._outbox.recover_stale_sending(
            stale_after=timedelta(seconds=self._settings.telegram_stale_sending_seconds),
            now=now,
        )
        self._runtime.record_recovered_unknown(recovered)
        try:
            self._discover(now)
            self._runtime.record_poll(now)
        except (BackendError, RenderError, ValueError) as error:
            code = getattr(error, "code", "telegram_discovery_error")
            self._runtime.record_error(str(code))
            LOGGER.warning("Telegram snapshot discovery deferred: code=%s", code)
        self._drain(now)

    def _discover(self, now: datetime) -> None:
        cutoff = now - timedelta(hours=self._settings.telegram_max_snapshot_age_hours)
        snapshots = []
        page_size = self._settings.telegram_snapshot_page_size
        for page in range(self._settings.telegram_snapshot_max_pages):
            page_items = self._snapshot_client.list_snapshots(
                limit=page_size,
                offset=page * page_size,
            )
            snapshots.extend(page_items)
            if len(page_items) < page_size:
                break
            if page_items and min(item.scheduled_for for item in page_items) < cutoff:
                break
        else:
            raise BackendError("backend_snapshot_page_limit_exceeded", retryable=False)

        destination = self._settings.telegram_destination_chat_id
        template = self._settings.telegram_mini_app_url_template
        assert destination is not None
        assert template is not None
        for snapshot in sorted(snapshots, key=lambda item: (item.scheduled_for, item.id)):
            if snapshot.organization_id != self._settings.nexolab_backend_organization_id:
                raise BackendError("backend_organization_mismatch", retryable=False)
            if snapshot.scheduled_for > now or snapshot.scheduled_for < cutoff:
                continue
            rendered = render_report(
                snapshot,
                mini_app_url_template=template,
                max_chars=self._settings.telegram_message_max_chars,
            )
            self._outbox.enqueue(
                snapshot,
                destination,
                rendered,
                destination_message_thread_id=self._settings.telegram_destination_message_thread_id,
                now=now,
            )

    def _drain(self, now: datetime) -> None:
        for _ in range(self._settings.telegram_max_deliveries_per_run):
            delivery = self._outbox.claim_next_for_destination(
                self._settings.telegram_destination_chat_id or "",
                destination_message_thread_id=self._settings.telegram_destination_message_thread_id,
                now=now,
            )
            if delivery is None:
                return
            try:
                result = self._telegram_client.send_message(
                    chat_id=delivery.destination_chat_id,
                    text=delivery.text,
                    button_url=delivery.button_url,
                    message_thread_id=delivery.destination_message_thread_id,
                )
                self._outbox.mark_sent(
                    delivery.id,
                    telegram_message_id=result.message_id,
                    now=now,
                )
                self._runtime.record_send(now)
            except TelegramApiError as error:
                self._runtime.record_error(error.code)
                if error.retryable and delivery.attempts < self._settings.telegram_max_attempts:
                    delay = self._retry_delay(delivery.attempts, error.retry_after_seconds)
                    self._outbox.mark_retry(
                        delivery.id,
                        delay=timedelta(seconds=delay),
                        error_code=error.code,
                        now=now,
                    )
                else:
                    self._outbox.mark_failed(delivery.id, error_code=error.code, now=now)
                LOGGER.warning(
                    "Telegram delivery attempt finished with error: delivery_id=%s snapshot_id=%s code=%s",
                    delivery.id,
                    delivery.snapshot_id,
                    error.code,
                )

    def _retry_delay(self, attempts: int, retry_after: float | None) -> float:
        exponent = max(0, attempts - 1)
        delay = min(
            self._settings.telegram_retry_initial_seconds * (2**exponent),
            self._settings.telegram_retry_max_seconds,
        )
        if retry_after is not None:
            delay = max(delay, retry_after)
        return min(delay, self._settings.telegram_retry_max_seconds)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(UTC)
