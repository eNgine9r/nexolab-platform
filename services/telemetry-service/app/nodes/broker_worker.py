from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.nodes.broker_adapter import BrokerControlAdapterError
from app.nodes.broker_control import BrokerControlState
from app.nodes.broker_models import CentralNodeBrokerCommand
from app.nodes.broker_repository import (
    BrokerControlEnvelopeError,
    BrokerControlRepository,
)


LOGGER = logging.getLogger("nexolab.telemetry.broker_control")


class BrokerControlAdapter(Protocol):
    def apply(self, command: CentralNodeBrokerCommand, secret: str | None) -> None: ...


@dataclass(frozen=True, slots=True)
class BrokerControlRunResult:
    recovered: int = 0
    claimed: int = 0
    applied: int = 0
    retried: int = 0
    failed: int = 0


class BrokerControlWorker:
    def __init__(
        self,
        *,
        database: Database,
        repository: BrokerControlRepository,
        adapter: BrokerControlAdapter,
        poll_interval_seconds: float,
        max_commands_per_run: int,
        max_attempts: int,
        retry_initial_seconds: float,
        retry_max_seconds: float,
        stale_lock_seconds: float,
    ) -> None:
        self._database = database
        self._repository = repository
        self._adapter = adapter
        self._poll_interval_seconds = poll_interval_seconds
        self._max_commands_per_run = max_commands_per_run
        self._max_attempts = max_attempts
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._stale_lock_seconds = stale_lock_seconds
        self._stop = Event()
        self._thread = Thread(
            target=self._run,
            name="broker-control-worker",
            daemon=True,
        )

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def run_once(self, *, now: datetime | None = None) -> BrokerControlRunResult:
        observed_at = _aware_utc(now or datetime.now(UTC))
        recovered = self._recover_stale_processing(observed_at)
        claimed_count = 0
        applied_count = 0
        retried_count = 0
        failed_count = 0

        for _ in range(self._max_commands_per_run):
            try:
                claimed = self._repository.claim_next(now=observed_at)
            except BrokerControlEnvelopeError:
                failed_count += 1
                LOGGER.error(
                    "Broker-control command failed encrypted-envelope authentication"
                )
                continue

            if claimed is None:
                break
            claimed_count += 1
            command = claimed.command

            try:
                self._adapter.apply(command, claimed.secret)
            except BrokerControlAdapterError as error:
                if not error.retryable or command.attempts >= self._max_attempts:
                    self._repository.mark_failed(
                        command.id,
                        error_code=error.code,
                        error_detail=error.detail,
                        now=observed_at,
                    )
                    failed_count += 1
                    LOGGER.error(
                        "Broker-control command failed terminally: command_id=%s "
                        "node_id=%s operation=%s error_code=%s attempts=%d",
                        command.id,
                        command.node_id,
                        command.operation,
                        error.code,
                        command.attempts,
                    )
                else:
                    delay = self._retry_delay(command.attempts)
                    self._repository.mark_retry(
                        command.id,
                        delay=delay,
                        error_code=error.code,
                        error_detail=error.detail,
                        now=observed_at,
                    )
                    retried_count += 1
                    LOGGER.warning(
                        "Broker-control command scheduled for retry: command_id=%s "
                        "node_id=%s operation=%s error_code=%s attempts=%d "
                        "delay_seconds=%.3f",
                        command.id,
                        command.node_id,
                        command.operation,
                        error.code,
                        command.attempts,
                        delay.total_seconds(),
                    )
                continue
            except Exception:  # noqa: BLE001 - worker process boundary
                code = "broker_worker_unexpected_error"
                detail = "broker-control adapter failed unexpectedly"
                if command.attempts >= self._max_attempts:
                    self._repository.mark_failed(
                        command.id,
                        error_code=code,
                        error_detail=detail,
                        now=observed_at,
                    )
                    failed_count += 1
                else:
                    delay = self._retry_delay(command.attempts)
                    self._repository.mark_retry(
                        command.id,
                        delay=delay,
                        error_code=code,
                        error_detail=detail,
                        now=observed_at,
                    )
                    retried_count += 1
                LOGGER.exception(
                    "Unexpected broker-control adapter failure: command_id=%s node_id=%s",
                    command.id,
                    command.node_id,
                )
                continue

            self._repository.mark_applied(command.id, now=observed_at)
            applied_count += 1
            LOGGER.info(
                "Broker-control command applied: command_id=%s node_id=%s operation=%s",
                command.id,
                command.node_id,
                command.operation,
            )

        return BrokerControlRunResult(
            recovered=recovered,
            claimed=claimed_count,
            applied=applied_count,
            retried=retried_count,
            failed=failed_count,
        )

    def _retry_delay(self, attempts: int) -> timedelta:
        exponent = max(0, attempts - 1)
        seconds = min(
            self._retry_initial_seconds * (2**exponent),
            self._retry_max_seconds,
        )
        return timedelta(seconds=seconds)

    def _recover_stale_processing(self, now: datetime) -> int:
        cutoff = now - timedelta(seconds=self._stale_lock_seconds)
        recovered = 0
        with Session(self._database.engine) as session:
            with session.begin():
                rows = list(
                    session.scalars(
                        select(CentralNodeBrokerCommand)
                        .where(
                            CentralNodeBrokerCommand.state
                            == BrokerControlState.PROCESSING.value,
                            CentralNodeBrokerCommand.locked_at.is_not(None),
                            CentralNodeBrokerCommand.locked_at <= cutoff,
                        )
                        .with_for_update(skip_locked=True)
                    )
                )
                for row in rows:
                    row.state = BrokerControlState.RETRYING.value
                    row.available_at = now
                    row.locked_at = None
                    row.error_code = "broker_worker_lock_expired"
                    row.error_detail = (
                        "processing lease expired before broker reconciliation completed"
                    )
                    row.updated_at = now
                    recovered += 1
        if recovered:
            LOGGER.warning(
                "Recovered stale broker-control processing leases: recovered=%d",
                recovered,
            )
        return recovered

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 - background worker boundary
                LOGGER.exception("Broker-control worker iteration failed")
            if self._stop.wait(self._poll_interval_seconds):
                break


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC)
