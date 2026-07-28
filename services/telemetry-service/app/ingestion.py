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


PersistenceWork = TelemetryWork | DeadLetterWork


class PostPersistProcessingError(RuntimeError):
    """Committed telemetry requires a retryable downstream processing replay."""


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
    ) -> None:
        self._database = database
        self._state = state
        self._on_persisted = on_persisted
        self._after_persist = after_persist
        self._authorize_ingress = authorize_ingress
        self._payload_max_bytes = payload_max_bytes
        self._dead_letter_payload_max_bytes = dead_letter_payload_max_bytes
        self._database_retry_initial_seconds = database_retry_initial_seconds
        self._database_retry_max_seconds = database_retry_max_seconds
        self._queue: Queue[PersistenceWork] = Queue(maxsize=queue_maxsize)
        self._state.set_queue_capacity(self._queue.maxsize)
        self._stop = Event()
        self._abort = Event()
        self._worker = Thread(
            target=self._run,
            name="telemetry-persistence",
            daemon=True,
        )

    def start(self) -> None:
        if not self._worker.is_alive():
            self._worker.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            LOGGER.error("Persistence worker did not drain before shutdown timeout")
            self._abort.set()
            self._worker.join(timeout=1.0)

    def submit_payload(self, payload: bytes, topic: str | None = None) -> bool:
        self._state.increment("received_total")
        received_at = datetime.now(UTC)

        if len(payload) > self._payload_max_bytes:
            return self._submit_dead_letter(
                payload,
                topic=topic,
                reason_code="payload_too_large",
                reason_detail=(
                    f"payload size {len(payload)} exceeds "
                    f"{self._payload_max_bytes} bytes"
                ),
            )

        try:
            decoded = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            return self._submit_dead_letter(
                payload,
                topic=topic,
                reason_code="invalid_utf8",
                reason_detail=str(exc),
            )

        try:
            raw = json.loads(decoded)
        except json.JSONDecodeError as exc:
            return self._submit_dead_letter(
                payload,
                topic=topic,
                reason_code="invalid_json",
                reason_detail=str(exc),
            )

        if not isinstance(raw, dict):
            return self._submit_dead_letter(
                payload,
                topic=topic,
                reason_code="payload_not_object",
                reason_detail="telemetry payload must be a JSON object",
            )

        try:
            event = TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            return self._submit_dead_letter(
                payload,
                topic=topic,
                reason_code="schema_validation",
                reason_detail=str(exc),
            )

        try:
            self._queue.put_nowait(
                TelemetryWork(
                    event=event,
                    raw=raw,
                    payload=payload,
                    topic=topic,
                    received_at=received_at,
                )
            )
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.set_error("ingestion queue is full")
            LOGGER.error("Ingestion queue is full; dropping event %s", event.event_id)
            return False

        self._state.increment("accepted_total")
        self._state.set_queue_size(self._queue.qsize())
        return True

    def _submit_dead_letter(
        self,
        payload: bytes,
        *,
        topic: str | None,
        reason_code: str,
        reason_detail: str,
    ) -> bool:
        self._state.increment("rejected_total")
        retained = payload[: self._dead_letter_payload_max_bytes]
        work = DeadLetterWork(
            payload=retained,
            payload_size=len(payload),
            payload_truncated=len(retained) != len(payload),
            reason_code=reason_code,
            reason_detail=reason_detail,
            topic=topic,
        )
        try:
            self._queue.put_nowait(work)
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.increment("dead_letter_dropped_total")
            self._state.set_error("ingestion queue is full; dead letter was dropped")
            LOGGER.error("Dead-letter queueing failed for reason %s", reason_code)
            return False

        self._state.increment("dead_letter_queued_total")
        self._state.set_queue_size(self._queue.qsize())
        LOGGER.warning("Rejected telemetry payload: reason=%s", reason_code)
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
