from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from app.nodes.broker_adapter import (
    BrokerControlAdapter,
    BrokerControlError,
    BrokerControlPermanentError,
)
from app.nodes.broker_crypto import BrokerCommandDecryptionError
from app.nodes.broker_repository import BrokerCommandOutbox


LOGGER = logging.getLogger(__name__)


class BrokerControlWorker:
    def __init__(
        self,
        *,
        outbox: BrokerCommandOutbox,
        adapter: BrokerControlAdapter,
        poll_interval_seconds: float = 1.0,
        lease_seconds: float = 30.0,
        retry_initial_seconds: float = 1.0,
        retry_max_seconds: float = 60.0,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("broker worker poll interval must be positive")
        if lease_seconds <= 0:
            raise ValueError("broker worker lease must be positive")
        if retry_initial_seconds <= 0 or retry_max_seconds < retry_initial_seconds:
            raise ValueError("broker worker retry configuration is invalid")
        self._outbox = outbox
        self._adapter = adapter
        self._poll_interval_seconds = poll_interval_seconds
        self._lease_seconds = lease_seconds
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="broker-control-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None

    def process_once(self, *, observed_at: datetime | None = None) -> bool:
        now = _aware_utc(observed_at or datetime.now(UTC))
        command = self._outbox.claim_next(
            lease_seconds=self._lease_seconds,
            observed_at=now,
        )
        if command is None:
            return False
        try:
            secret = (
                self._outbox.decrypt_secret(command)
                if command.command_type == "upsert_credential"
                else None
            )
            self._adapter.apply(command, secret=secret)
        except BrokerCommandDecryptionError:
            self._outbox.mark_failed(
                command.id,
                error_code=BrokerCommandDecryptionError.code,
                error_summary="encrypted broker command secret failed validation",
                observed_at=now,
            )
            LOGGER.error(
                "broker command failed closed command_id=%s code=%s",
                command.id,
                BrokerCommandDecryptionError.code,
            )
            return True
        except BrokerControlError as error:
            self._handle_control_error(command.id, command.attempts, command.max_attempts, error, now)
            return True
        except Exception:
            error = BrokerControlPermanentError("unexpected broker control failure")
            self._handle_control_error(command.id, command.attempts, command.max_attempts, error, now)
            LOGGER.exception(
                "unexpected broker command failure command_id=%s",
                command.id,
            )
            return True
        self._outbox.mark_applied(command.id, observed_at=now)
        LOGGER.info(
            "broker command applied command_id=%s command_type=%s attempts=%s",
            command.id,
            command.command_type,
            command.attempts,
        )
        return True

    def _handle_control_error(
        self,
        command_id: str,
        attempts: int,
        max_attempts: int,
        error: BrokerControlError,
        observed_at: datetime,
    ) -> None:
        summary = _safe_summary(str(error))
        if not error.retryable or attempts >= max_attempts:
            self._outbox.mark_failed(
                command_id,
                error_code=error.code,
                error_summary=summary,
                observed_at=observed_at,
            )
            LOGGER.error(
                "broker command terminal failure command_id=%s code=%s attempts=%s",
                command_id,
                error.code,
                attempts,
            )
            return
        delay = min(
            self._retry_max_seconds,
            self._retry_initial_seconds * (2 ** max(0, attempts - 1)),
        )
        self._outbox.mark_retry(
            command_id,
            retry_at=observed_at + timedelta(seconds=delay),
            error_code=error.code,
            error_summary=summary,
            observed_at=observed_at,
        )
        LOGGER.warning(
            "broker command scheduled for retry command_id=%s code=%s attempts=%s retry_seconds=%s",
            command_id,
            error.code,
            attempts,
            delay,
        )

    def _run(self) -> None:
        while not self._stop.is_set():
            processed = self.process_once()
            if not processed:
                self._stop.wait(self._poll_interval_seconds)


def _safe_summary(value: str) -> str:
    normalized = " ".join(value.split())
    return (normalized or "broker control operation failed")[:1024]


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)
