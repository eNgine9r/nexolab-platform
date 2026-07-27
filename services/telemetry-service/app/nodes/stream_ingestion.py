from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Event, Thread

from pydantic import ValidationError

from app.db import Database
from app.nodes.domain import NodeTopicStream, ParsedNodeTopic, parse_node_topic
from app.nodes.stream_contracts import NodeHealthEvent, NodeStatusEvent
from app.nodes.stream_repository import (
    NodeStreamAuthorizationError,
    NodeStreamReplayError,
    NodeStreamRepository,
)
from app.state import RuntimeState


LOGGER = logging.getLogger("nexolab.nodes.streams")
NODE_STREAM_SCHEMA_REASON = "node_stream_schema"
NODE_STREAM_AUTHORIZATION_REASON = "node_authorization"
NODE_STREAM_REPLAY_REASON = "node_replay"


@dataclass(frozen=True, slots=True)
class NodeStreamWork:
    topic: str
    parsed_topic: ParsedNodeTopic
    payload: bytes
    event: NodeHealthEvent | NodeStatusEvent
    received_at: datetime


class NodeStreamIngestor:
    """Persist node health/status outside the telemetry sample pipeline."""

    def __init__(
        self,
        database: Database,
        state: RuntimeState,
        *,
        queue_maxsize: int = 1000,
        payload_max_bytes: int = 65_536,
        dead_letter_payload_max_bytes: int = 65_536,
        database_retry_initial_seconds: float = 0.25,
        database_retry_max_seconds: float = 5.0,
    ) -> None:
        self._database = database
        self._state = state
        self._repository = NodeStreamRepository(database)
        self._payload_max_bytes = payload_max_bytes
        self._dead_letter_payload_max_bytes = dead_letter_payload_max_bytes
        self._database_retry_initial_seconds = database_retry_initial_seconds
        self._database_retry_max_seconds = database_retry_max_seconds
        self._queue: Queue[NodeStreamWork] = Queue(maxsize=queue_maxsize)
        self._stop = Event()
        self._abort = Event()
        self._worker = Thread(
            target=self._run,
            name="node-stream-persistence",
            daemon=True,
        )

    def start(self) -> None:
        if not self._worker.is_alive():
            self._worker.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            LOGGER.error("Node stream worker did not drain before shutdown timeout")
            self._abort.set()
            self._worker.join(timeout=1.0)

    def submit_payload(self, payload: bytes, *, topic: str) -> bool:
        received_at = datetime.now(UTC)
        if len(payload) > self._payload_max_bytes:
            self._persist_dead_letter(
                payload,
                topic=topic,
                reason_code="payload_too_large",
                reason_detail=(
                    f"node stream payload size {len(payload)} exceeds "
                    f"{self._payload_max_bytes} bytes"
                ),
            )
            return False
        try:
            parsed_topic = parse_node_topic(topic)
        except ValueError as error:
            self._persist_dead_letter(
                payload,
                topic=topic,
                reason_code=NODE_STREAM_AUTHORIZATION_REASON,
                reason_detail=str(error),
            )
            return False
        if parsed_topic.stream not in {NodeTopicStream.HEALTH, NodeTopicStream.STATUS}:
            self._persist_dead_letter(
                payload,
                topic=topic,
                reason_code=NODE_STREAM_SCHEMA_REASON,
                reason_detail="node stream dispatcher accepts only health and status",
            )
            return False
        try:
            raw = json.loads(payload.decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("node stream payload must be a JSON object")
            event = (
                NodeHealthEvent.model_validate(raw)
                if parsed_topic.stream is NodeTopicStream.HEALTH
                else NodeStatusEvent.model_validate(raw)
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as error:
            self._persist_dead_letter(
                payload,
                topic=topic,
                reason_code=NODE_STREAM_SCHEMA_REASON,
                reason_detail=str(error),
            )
            return False

        try:
            self._queue.put_nowait(
                NodeStreamWork(
                    topic=topic,
                    parsed_topic=parsed_topic,
                    payload=payload,
                    event=event,
                    received_at=received_at,
                )
            )
        except Full:
            self._state.increment("queue_dropped_total")
            self._state.set_error("node stream ingestion queue is full")
            LOGGER.error("Node stream queue is full; dropping event %s", event.event_id)
            return False
        return True

    def _persist(self, work: NodeStreamWork) -> None:
        scoped = self._repository.for_organization(work.parsed_topic.organization_id)
        if isinstance(work.event, NodeHealthEvent):
            _, replayed = scoped.persist_health(
                work.event,
                topic=work.topic,
                received_at=work.received_at,
            )
        else:
            _, replayed = scoped.persist_status(
                work.event,
                topic=work.topic,
                received_at=work.received_at,
            )
        if replayed:
            self._state.increment("duplicate_total")
        self._state.set_error(None)

    def _persist_dead_letter(
        self,
        payload: bytes,
        *,
        topic: str,
        reason_code: str,
        reason_detail: str,
    ) -> None:
        retained = payload[: self._dead_letter_payload_max_bytes]
        self._database.persist_dead_letter(
            payload=retained,
            payload_size=len(payload),
            payload_truncated=len(retained) != len(payload),
            reason_code=reason_code,
            reason_detail=reason_detail,
            topic=topic,
        )
        self._state.increment("rejected_total")
        self._state.mark_dead_letter_persisted(reason_code)
        LOGGER.warning("Rejected node stream payload: topic=%s reason=%s", topic, reason_detail)

    def _run(self) -> None:
        pending: NodeStreamWork | None = None
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
            try:
                self._persist(pending)
            except NodeStreamReplayError as error:
                self._persist_dead_letter(
                    pending.payload,
                    topic=pending.topic,
                    reason_code=NODE_STREAM_REPLAY_REASON,
                    reason_detail=str(error),
                )
            except NodeStreamAuthorizationError as error:
                self._persist_dead_letter(
                    pending.payload,
                    topic=pending.topic,
                    reason_code=NODE_STREAM_AUTHORIZATION_REASON,
                    reason_detail=str(error),
                )
            except Exception as error:  # noqa: BLE001 - retryable persistence boundary
                self._state.increment("persistence_failure_total")
                self._state.increment("database_retry_total")
                self._state.mark_database_failure(
                    f"node stream persistence failed: {error}"
                )
                LOGGER.warning(
                    "Node stream persistence deferred; retrying in %.2fs: %s",
                    retry_delay,
                    error,
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
