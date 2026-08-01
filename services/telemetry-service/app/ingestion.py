from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any

from pydantic import ValidationError

from app.contracts import TelemetryEvent
from app.db import Database
from app.durable_spool import (
    DurableIngestionSpool,
    DurableSpoolCapacityError,
    DurableSpoolError,
    SpoolRecord,
)
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.ingestion")

IngressAuthorizer = Callable[
    [TelemetryEvent, str | None, datetime],
    tuple[bool, str, str],
]


@dataclass(frozen=True)
class TelemetryWork:
    event: TelemetryEvent
    raw: dict[str, Any]
    payload: bytes = b""
    topic: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class DeadLetterWork:
    payload: bytes
    payload_size: int
    payload_truncated: bool
    reason_code: str
    reason_detail: str
    topic: str | None
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class DurableStageResult:
    staged: bool
    accepted: bool
    duplicate: bool = False
    record_id: int | None = None
    error: str | None = None


PersistenceWork = TelemetryWork | DeadLetterWork


class PostPersistProcessingError(RuntimeError):
    """Committed telemetry requires a retryable downstream processing replay."""


class InvalidSpoolRecordError(RuntimeError):
    """A durable record cannot be decoded by the current ingestion contract."""


class TelemetryIngestor:
    def __init__(
        self,
        database: Database,
        state: RuntimeState,
        queue_maxsize: int,
        on_persisted: Callable[[dict[str, Any]], None] | None = None,
        *,
        after_persist: Callable[[dict[str, Any]], None] | None = None,
        authorize_ingress: IngressAuthorizer | None = None,
        payload_max_bytes: int = 262_144,
        dead_letter_payload_max_bytes: int = 65_536,
        database_retry_initial_seconds: float = 0.25,
        database_retry_max_seconds: float = 5.0,
        durable_spool: DurableIngestionSpool | None = None,
        spool_poll_interval_seconds: float = 0.1,
    ) -> None:
        if spool_poll_interval_seconds <= 0:
            raise ValueError("spool poll interval must be positive")
        self._database = database
        self._state = state
        self._state.set_queue_capacity(queue_maxsize)
        self._on_persisted = on_persisted
        self._after_persist = after_persist
        self._authorize_ingress = authorize_ingress
        self._payload_max_bytes = payload_max_bytes
        self._dead_letter_payload_max_bytes = dead_letter_payload_max_bytes
        self._database_retry_initial_seconds = database_retry_initial_seconds
        self._database_retry_max_seconds = database_retry_max_seconds
        self._spool_poll_interval_seconds = spool_poll_interval_seconds
        self._queue: Queue[PersistenceWork] = Queue(maxsize=queue_maxsize)
        self._durable_spool = durable_spool
        self._startup_spool_max_id = 0
        self._stop = Event()
        self._abort = Event()
        self._worker = Thread(
            target=self._run,
            name="telemetry-persistence",
            daemon=True,
        )
        if durable_spool is not None:
            self._initialize_spool_state(durable_spool)

    @property
    def durable_enabled(self) -> bool:
        return self._durable_spool is not None

    def attach_durable_spool(self, spool: DurableIngestionSpool) -> None:
        if self._worker.is_alive():
            raise RuntimeError("durable spool must be attached before ingestion starts")
        if self._durable_spool is not None and self._durable_spool is not spool:
            raise RuntimeError("a different durable spool is already attached")
        self._durable_spool = spool
        self._initialize_spool_state(spool)

    def _initialize_spool_state(self, spool: DurableIngestionSpool) -> None:
        self._state.set_spool_capacity(
            max_records=spool.max_records,
            max_bytes=spool.max_bytes,
        )
        stats = spool.stats()
        self._startup_spool_max_id = stats.max_record_id
        if stats.pending_records:
            self._state.increment("spool_recovered_total", stats.pending_records)
        self._state.set_spool_ready(True)
        self._state.set_spool_stats(
            pending_records=stats.pending_records,
            terminal_records=stats.terminal_records,
            payload_bytes=stats.payload_bytes,
            oldest_pending_age_seconds=stats.oldest_pending_age_seconds,
        )

    def start(self) -> None:
        if not self._worker.is_alive():
            self._worker.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            LOGGER.error("Persistence worker did not stop before shutdown timeout")
            self._abort.set()
            self._worker.join(timeout=1.0)

    def submit_payload(self, payload: bytes, topic: str | None = None) -> bool:
        if self._durable_spool is not None:
            return self.stage_mqtt_payload(
                payload,
                topic=topic,
                delivery_key=None,
            ).accepted
        work = self._decode_submission(payload, topic=topic)
        if isinstance(work, DeadLetterWork):
            return self._enqueue_dead_letter(work)

        try:
            self._queue.put_nowait(work)
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.set_error("ingestion queue is full")
            LOGGER.error(
                "Ingestion queue is full; dropping event %s",
                work.event.event_id,
            )
            return False

        self._state.increment("accepted_total")
        self._state.set_queue_size(self._queue.qsize())
        return True

    def stage_mqtt_payload(
        self,
        payload: bytes,
        *,
        topic: str | None,
        delivery_key: str | None,
        is_retry: bool = False,
    ) -> DurableStageResult:
        spool = self._durable_spool
        if spool is None:
            raise RuntimeError("durable MQTT staging requires an attached spool")

        work = self._decode_submission(
            payload,
            topic=topic,
            count_metrics=not is_retry,
        )
        try:
            if isinstance(work, TelemetryWork):
                append = spool.append_telemetry(
                    event_id=str(work.event.event_id),
                    payload=work.payload,
                    topic=work.topic,
                    received_at=work.received_at,
                    delivery_key=delivery_key,
                )
                self._state.increment("accepted_total")
                accepted = True
            else:
                append = spool.append_dead_letter(
                    payload=work.payload,
                    payload_size=work.payload_size,
                    payload_truncated=work.payload_truncated,
                    reason_code=work.reason_code,
                    reason_detail=work.reason_detail,
                    topic=work.topic,
                    received_at=work.received_at,
                    delivery_key=delivery_key,
                )
                self._state.increment("dead_letter_queued_total")
                accepted = False
                LOGGER.warning(
                    "Rejected telemetry payload durably staged: reason=%s",
                    work.reason_code,
                )
        except DurableSpoolCapacityError as exc:
            self._state.increment("spool_capacity_failure_total")
            self._state.set_error(str(exc))
            self._refresh_spool_state()
            LOGGER.error("Durable ingestion spool capacity reached: %s", exc)
            return DurableStageResult(
                staged=False,
                accepted=False,
                error=str(exc),
            )
        except DurableSpoolError as exc:
            self._state.increment("spool_error_total")
            self._state.set_spool_ready(False)
            self._state.set_error(str(exc))
            LOGGER.exception("Durable ingestion staging failed")
            return DurableStageResult(
                staged=False,
                accepted=False,
                error=str(exc),
            )

        if append.duplicate:
            self._state.increment("spool_duplicate_total")
        else:
            self._state.increment("spool_staged_total")
        self._state.set_spool_ready(True)
        self._state.set_error(None)
        self._refresh_spool_state()
        return DurableStageResult(
            staged=True,
            accepted=accepted,
            duplicate=append.duplicate,
            record_id=append.record_id,
        )

    def _decode_submission(
        self,
        payload: bytes,
        *,
        topic: str | None,
        count_metrics: bool = True,
    ) -> PersistenceWork:
        if count_metrics:
            self._state.increment("received_total")
        received_at = datetime.now(UTC)

        if len(payload) > self._payload_max_bytes:
            return self._dead_letter_work(
                payload,
                topic=topic,
                received_at=received_at,
                reason_code="payload_too_large",
                reason_detail=(
                    f"payload size {len(payload)} exceeds "
                    f"{self._payload_max_bytes} bytes"
                ),
                count_metrics=count_metrics,
            )

        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            return self._dead_letter_work(
                payload,
                topic=topic,
                received_at=received_at,
                reason_code="invalid_utf8",
                reason_detail=str(exc),
                count_metrics=count_metrics,
            )

        try:
            raw = json.loads(decoded)
        except json.JSONDecodeError as exc:
            return self._dead_letter_work(
                payload,
                topic=topic,
                received_at=received_at,
                reason_code="invalid_json",
                reason_detail=str(exc),
                count_metrics=count_metrics,
            )

        if not isinstance(raw, dict):
            return self._dead_letter_work(
                payload,
                topic=topic,
                received_at=received_at,
                reason_code="payload_not_object",
                reason_detail="telemetry payload must be a JSON object",
                count_metrics=count_metrics,
            )

        try:
            event = TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            return self._dead_letter_work(
                payload,
                topic=topic,
                received_at=received_at,
                reason_code="schema_validation",
                reason_detail=str(exc),
                count_metrics=count_metrics,
            )

        return TelemetryWork(
            event=event,
            raw=raw,
            payload=payload,
            topic=topic,
            received_at=received_at,
        )

    def _dead_letter_work(
        self,
        payload: bytes,
        *,
        topic: str | None,
        received_at: datetime,
        reason_code: str,
        reason_detail: str,
        count_metrics: bool,
    ) -> DeadLetterWork:
        if count_metrics:
            self._state.increment("rejected_total")
        retained = payload[: self._dead_letter_payload_max_bytes]
        return DeadLetterWork(
            payload=retained,
            payload_size=len(payload),
            payload_truncated=len(retained) != len(payload),
            reason_code=reason_code,
            reason_detail=reason_detail,
            topic=topic,
            received_at=received_at,
        )

    def _enqueue_dead_letter(self, work: DeadLetterWork) -> bool:
        try:
            self._queue.put_nowait(work)
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.increment("dead_letter_dropped_total")
            self._state.set_error("ingestion queue is full; dead letter was dropped")
            LOGGER.error("Dead-letter queueing failed for reason %s", work.reason_code)
            return False

        self._state.increment("dead_letter_queued_total")
        self._state.set_queue_size(self._queue.qsize())
        LOGGER.warning("Rejected telemetry payload: reason=%s", work.reason_code)
        return False

    def _persist(self, work: PersistenceWork) -> None:
        if isinstance(work, TelemetryWork):
            if self._authorize_ingress is not None:
                allowed, reason_code, reason_detail = self._authorize_ingress(
                    work.event,
                    work.topic,
                    work.received_at,
                )
                if not allowed:
                    self._state.increment("rejected_total")
                    self._state.increment("dead_letter_queued_total")
                    self._persist_authorization_dead_letter(
                        work,
                        reason_code=reason_code,
                        reason_detail=reason_detail,
                    )
                    return

            inserted = self._database.persist(work.event, work.raw)
            normalized = work.event.normalized_payload()
            if inserted:
                self._state.mark_persisted(work.event.captured_at)
                if self._on_persisted is not None:
                    try:
                        self._on_persisted(normalized)
                    except Exception:  # noqa: BLE001 - best-effort live boundary
                        self._state.increment("websocket_publish_error_total")
                        LOGGER.exception(
                            "Failed to publish persisted event %s to live clients",
                            work.event.event_id,
                        )
            else:
                self._state.mark_database_success()
                self._state.increment("duplicate_total")
                self._state.set_error(None)

            if self._after_persist is not None:
                try:
                    self._after_persist(normalized)
                except Exception as exc:  # noqa: BLE001 - retryable pipeline boundary
                    raise PostPersistProcessingError(
                        f"post-persist processing failed for {work.event.event_id}: {exc}"
                    ) from exc
            return

        self._database.persist_dead_letter(
            payload=work.payload,
            payload_size=work.payload_size,
            payload_truncated=work.payload_truncated,
            reason_code=work.reason_code,
            reason_detail=work.reason_detail,
            topic=work.topic,
        )
        self._state.mark_dead_letter_persisted(work.reason_code)
        self._state.set_error(None)

    def _persist_authorization_dead_letter(
        self,
        work: TelemetryWork,
        *,
        reason_code: str,
        reason_detail: str,
    ) -> None:
        retained = work.payload[: self._dead_letter_payload_max_bytes]
        self._database.persist_dead_letter(
            payload=retained,
            payload_size=len(work.payload),
            payload_truncated=len(retained) != len(work.payload),
            reason_code=reason_code,
            reason_detail=reason_detail,
            topic=work.topic,
        )
        self._state.mark_dead_letter_persisted(reason_code)
        self._state.set_error(None)
        LOGGER.warning(
            "Rejected telemetry after node authorization: event=%s reason=%s",
            work.event.event_id,
            reason_detail,
        )

    def _run(self) -> None:
        if self._durable_spool is not None:
            self._run_durable()
            return
        self._run_memory()

    def _run_durable(self) -> None:
        spool = self._durable_spool
        if spool is None:
            return
        retry_delay = self._database_retry_initial_seconds

        while not self._abort.is_set() and not self._stop.is_set():
            try:
                record = spool.oldest_pending()
            except DurableSpoolError as exc:
                self._state.increment("spool_error_total")
                self._state.set_spool_ready(False)
                self._state.set_error(str(exc))
                LOGGER.exception("Failed to read the durable ingestion spool")
                self._stop.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue

            if record is None:
                retry_delay = self._database_retry_initial_seconds
                self._refresh_spool_state()
                self._stop.wait(self._spool_poll_interval_seconds)
                continue

            try:
                work = self._work_from_spool(record)
                self._persist(work)
            except InvalidSpoolRecordError as exc:
                try:
                    spool.mark_terminal(record.record_id, str(exc))
                except DurableSpoolError as spool_exc:
                    self._state.increment("spool_error_total")
                    self._state.set_spool_ready(False)
                    self._state.set_error(str(spool_exc))
                    LOGGER.exception("Failed to quarantine invalid spool record")
                    self._stop.wait(retry_delay)
                    continue
                self._state.increment("spool_terminal_total")
                self._state.set_error(str(exc))
                LOGGER.error(
                    "Durable spool record %s quarantined: %s",
                    record.record_id,
                    exc,
                )
                self._refresh_spool_state()
                retry_delay = self._database_retry_initial_seconds
                continue
            except PostPersistProcessingError as exc:
                self._record_spool_retry(record, exc)
                self._state.increment("post_persist_retry_total")
                self._state.set_error(str(exc))
                LOGGER.warning(
                    "Post-persist processing deferred; retrying in %.2fs: %s",
                    retry_delay,
                    exc,
                )
                self._stop.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - retryable persistence boundary
                self._record_spool_retry(record, exc)
                self._state.increment("persistence_failure_total")
                self._state.increment("database_retry_total")
                self._state.mark_database_failure(
                    f"database persistence failed: {exc}"
                )
                LOGGER.warning(
                    "Database persistence deferred; retrying in %.2fs: %s",
                    retry_delay,
                    exc,
                )
                self._stop.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue

            try:
                spool.delete(record.record_id)
            except DurableSpoolError as exc:
                self._state.increment("spool_error_total")
                self._state.set_spool_ready(False)
                self._state.set_error(str(exc))
                LOGGER.exception(
                    "Persisted record %s remains in spool; idempotent replay will retry",
                    record.record_id,
                )
                self._stop.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue

            if record.record_id <= self._startup_spool_max_id or record.attempts > 0:
                self._state.increment("spool_replayed_total")
            self._state.set_spool_ready(True)
            self._state.set_error(None)
            self._refresh_spool_state()
            retry_delay = self._database_retry_initial_seconds

    def _record_spool_retry(self, record: SpoolRecord, error: Exception) -> None:
        spool = self._durable_spool
        if spool is None:
            return
        try:
            spool.mark_attempt(record.record_id, str(error))
        except DurableSpoolError as exc:
            self._state.increment("spool_error_total")
            self._state.set_spool_ready(False)
            self._state.set_error(str(exc))
            LOGGER.exception("Failed to record durable spool retry metadata")
        self._refresh_spool_state()

    def _work_from_spool(self, record: SpoolRecord) -> PersistenceWork:
        if record.work_type == "dead_letter":
            if record.reason_code is None:
                raise InvalidSpoolRecordError(
                    f"dead-letter record {record.record_id} has no reason code"
                )
            return DeadLetterWork(
                payload=record.payload,
                payload_size=record.payload_size,
                payload_truncated=record.payload_truncated,
                reason_code=record.reason_code,
                reason_detail=record.reason_detail or "",
                topic=record.topic,
                received_at=record.received_at,
            )

        if record.work_type != "telemetry":
            raise InvalidSpoolRecordError(
                f"record {record.record_id} has unsupported type {record.work_type}"
            )
        try:
            decoded = record.payload.decode("utf-8")
            raw = json.loads(decoded)
            if not isinstance(raw, dict):
                raise ValueError("telemetry payload must be a JSON object")
            event = TelemetryEvent.model_validate(raw)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as exc:
            raise InvalidSpoolRecordError(
                f"telemetry record {record.record_id} is no longer decodable: {exc}"
            ) from exc
        if record.event_id is None or str(event.event_id) != record.event_id:
            raise InvalidSpoolRecordError(
                f"telemetry record {record.record_id} event_id mismatch"
            )
        return TelemetryWork(
            event=event,
            raw=raw,
            payload=record.payload,
            topic=record.topic,
            received_at=record.received_at,
        )

    def _refresh_spool_state(self) -> None:
        spool = self._durable_spool
        if spool is None:
            return
        try:
            stats = spool.stats()
        except DurableSpoolError as exc:
            self._state.increment("spool_error_total")
            self._state.set_spool_ready(False)
            self._state.set_error(str(exc))
            return
        self._state.set_spool_stats(
            pending_records=stats.pending_records,
            terminal_records=stats.terminal_records,
            payload_bytes=stats.payload_bytes,
            oldest_pending_age_seconds=stats.oldest_pending_age_seconds,
        )

    def _run_memory(self) -> None:
        pending: PersistenceWork | None = None
        retry_delay = self._database_retry_initial_seconds

        while (
            not self._abort.is_set()
            and (not self._stop.is_set() or pending is not None or not self._queue.empty())
        ):
            if pending is None:
                try:
                    pending = self._queue.get(timeout=0.5)
                except Empty:
                    continue
                self._state.set_queue_size(self._queue.qsize() + 1)

            try:
                self._persist(pending)
            except PostPersistProcessingError as exc:
                self._state.increment("post_persist_retry_total")
                self._state.set_error(str(exc))
                LOGGER.warning(
                    "Post-persist processing deferred; retrying in %.2fs: %s",
                    retry_delay,
                    exc,
                )
                self._abort.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue
            except Exception as exc:  # noqa: BLE001 - worker boundary
                self._state.increment("persistence_failure_total")
                self._state.increment("database_retry_total")
                self._state.mark_database_failure(
                    f"database persistence failed: {exc}"
                )
                LOGGER.warning(
                    "Database persistence deferred; retrying in %.2fs: %s",
                    retry_delay,
                    exc,
                )
                self._abort.wait(retry_delay)
                retry_delay = min(
                    retry_delay * 2,
                    self._database_retry_max_seconds,
                )
                continue

            self._queue.task_done()
            pending = None
            retry_delay = self._database_retry_initial_seconds
            self._state.set_queue_size(self._queue.qsize())

        if pending is not None:
            self._state.increment("queue_dropped_total")
            self._state.set_error("shutdown abandoned an unpersisted queue item")
