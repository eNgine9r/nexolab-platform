from __future__ import annotations

import json
import logging
from collections.abc import Callable
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Any

from pydantic import ValidationError

from app.contracts import TelemetryEvent
from app.db import Database
from app.state import RuntimeState

LOGGER = logging.getLogger("nexolab.telemetry.ingestion")


class TelemetryIngestor:
    def __init__(
        self,
        database: Database,
        state: RuntimeState,
        queue_maxsize: int,
        on_persisted: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._database = database
        self._state = state
        self._on_persisted = on_persisted
        self._queue: Queue[tuple[TelemetryEvent, dict[str, Any]]] = Queue(
            maxsize=queue_maxsize
        )
        self._stop = Event()
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

    def submit_payload(self, payload: bytes) -> bool:
        self._state.increment("received_total")

        try:
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("telemetry payload must be a JSON object")
            event = TelemetryEvent.model_validate(raw)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            self._state.increment("rejected_total")
            self._state.set_error(f"invalid telemetry: {exc}")
            LOGGER.warning("Rejected telemetry payload: %s", exc)
            return False

        try:
            self._queue.put_nowait((event, raw))
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.set_error("ingestion queue is full")
            LOGGER.error("Ingestion queue is full; dropping event %s", event.event_id)
            return False

        self._state.increment("accepted_total")
        self._state.set_queue_size(self._queue.qsize())
        return True

    def _run(self) -> None:
        while not self._stop.is_set() or not self._queue.empty():
            try:
                event, raw = self._queue.get(timeout=0.5)
            except Empty:
                continue

            try:
                inserted = self._database.persist(event, raw)
                self._state.set_database_ready(True)
                if inserted:
                    self._state.mark_persisted()
                    if self._on_persisted is not None:
                        try:
                            self._on_persisted(event.normalized_payload())
                        except Exception:  # noqa: BLE001 - callback boundary
                            self._state.increment("websocket_publish_error_total")
                            LOGGER.exception(
                                "Failed to publish persisted event %s to live clients",
                                event.event_id,
                            )
                else:
                    self._state.increment("duplicate_total")
                    self._state.set_error(None)
            except Exception as exc:  # noqa: BLE001 - worker boundary
                self._state.set_database_ready(False)
                self._state.set_error(f"database persistence failed: {exc}")
                LOGGER.exception("Failed to persist event %s", event.event_id)
            finally:
                self._queue.task_done()
                self._state.set_queue_size(self._queue.qsize())
