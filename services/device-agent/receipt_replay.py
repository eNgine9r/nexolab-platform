"""Bounded source-only FIFO replay for future authenticated final-receipt mode.

NOT wired into DeviceAgent. A trusted caller must independently establish
installed broker ACL/identity and an authenticated receipt subscriber before
enabling receipt mode. MQTT QoS1 PUBACK is never a deletion authorization.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from collections.abc import Callable

from durable_receipt_v1 import NODE_ID, ReceiptProtocolError
from receipt_retention import CommittedReceiptQueue, _strict_local_pairs


class CommittedReceiptReplay:
    """One oldest telemetry event per attempt, with bounded exponential backoff.

    The caller supplies a publisher that returns True ONLY after MQTT QoS1
    PUBACK. A True result confirms broker acknowledgment, not central
    PostgreSQL commit. The caller handles authenticated final receipts via
    CommittedReceiptQueue.apply_committed_receipt(), separately.
    """

    def __init__(
        self,
        queue: CommittedReceiptQueue,
        *,
        organization_id: str,
        node_id: str,
        initial_retry_seconds: float = 5.0,
        max_retry_seconds: float = 300.0,
    ) -> None:
        try:
            canonical_org = str(uuid.UUID(organization_id))
        except (TypeError, AttributeError, ValueError) as exc:
            raise ValueError("invalid_organization_id") from exc
        if canonical_org != organization_id:
            raise ValueError("noncanonical_organization_id")
        if not isinstance(node_id, str) or not NODE_ID.fullmatch(node_id):
            raise ValueError("invalid_node_id")
        if (
            not math.isfinite(initial_retry_seconds)
            or not math.isfinite(max_retry_seconds)
            or initial_retry_seconds <= 0
            or max_retry_seconds < initial_retry_seconds
        ):
            raise ValueError("invalid_retry_budget")
        self._queue = queue
        self._organization_id = organization_id
        self._node_id = node_id
        self._topic = f"nexolab/v1/{organization_id}/{node_id}/telemetry"
        self._initial = initial_retry_seconds
        self._maximum = max_retry_seconds
        self._lock = threading.Lock()
        self._row_id: int | None = None
        self._next_due = 0.0
        self._row_attempts = 0
        self._attempts_total = 0
        self._pubacks_total = 0
        self._failures_total = 0

    def attempt_once(
        self,
        publish_qos1: Callable[[str, str], bool],
        *,
        now_monotonic: float,
    ) -> str:
        """Return empty/blocked/deferred/puback_waiting_receipt/retry_scheduled.

        One call invokes the network callback at most once. SQLite is never
        mutated; a final broker-PUBACK cannot cause queue deletion. Resends
        are idempotent at central ingestion by their original event_id and
        immutable node_sequence.
        """
        if not isinstance(now_monotonic, (int, float)) or not math.isfinite(
            now_monotonic
        ) or now_monotonic < 0:
            raise ValueError("invalid_monotonic_clock")
        if not callable(publish_qos1):
            raise TypeError("publisher_required")

        with self._lock:
            candidate = self._queue.oldest_receipt_replay_candidate()
            if candidate is None:
                self._row_id = None
                self._row_attempts = 0
                self._next_due = 0.0
                return "empty"
            row_id, event_id, topic, payload = candidate
            # Never interpret the legacy unscoped topic or other streams as
            # eligible for receipt-mode replay. Do not skip the oldest row.
            if topic != self._topic:
                return "blocked_foreign_queue_topic"
            try:
                body = json.loads(payload, object_pairs_hook=_strict_local_pairs)
            except ReceiptProtocolError:
                raise
            except (ValueError, TypeError) as exc:
                raise ReceiptProtocolError("invalid_local_replay_payload") from exc
            if (
                not isinstance(body, dict)
                or body.get("event_id") != event_id
                or body.get("node_id") != self._node_id
                or body.get("organization_id") not in (None, self._organization_id)
                or body.get("stream") not in (None, "telemetry")
                or type(body.get("node_sequence")) is not int
                or body["node_sequence"] < 1
            ):
                raise ReceiptProtocolError("invalid_local_replay_identity")
            try:
                if str(uuid.UUID(event_id)) != event_id:
                    raise ValueError("noncanonical_event_id")
            except (TypeError, ValueError, AttributeError) as exc:
                raise ReceiptProtocolError("invalid_local_replay_event_id") from exc

            if row_id != self._row_id:
                self._row_id = row_id
                self._row_attempts = 0
                self._next_due = 0.0
            if now_monotonic < self._next_due:
                return "deferred"

            self._row_attempts += 1
            self._attempts_total += 1
            # All attempts are throttled, including successful PUBACKs. A
            # stalled central subscriber cannot induce an unbounded flood.
            delay = min(
                self._maximum,
                self._initial * (2 ** min(self._row_attempts - 1, 30)),
            )
            self._next_due = now_monotonic + delay
            try:
                acknowledged = publish_qos1(topic, payload) is True
            except (OSError, ValueError, RuntimeError, TimeoutError):
                acknowledged = False
            if acknowledged:
                self._pubacks_total += 1
                return "puback_waiting_receipt"
            self._failures_total += 1
            return "retry_scheduled"

    def snapshot(self, *, now_monotonic: float) -> dict[str, object]:
        if not isinstance(now_monotonic, (int, float)) or not math.isfinite(
            now_monotonic
        ):
            raise ValueError("invalid_monotonic_clock")
        with self._lock:
            return {
                "schema_version": 1,
                "active_row_id": self._row_id,
                "row_attempts": self._row_attempts,
                "attempts_total": self._attempts_total,
                "broker_pubacks_total": self._pubacks_total,
                "publish_failures_total": self._failures_total,
                "next_retry_seconds": (
                    max(0.0, self._next_due - now_monotonic)
                    if self._row_id is not None
                    else None
                ),
                "postgres_committed": False,
            }
