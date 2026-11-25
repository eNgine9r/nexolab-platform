"""Bounded FIFO replay for authenticated final-receipt mode.

Driven by committed_receipt_mode.CommittedReceiptRuntime only when
DEVICE_AGENT_COMMITTED_RECEIPTS=enabled (#1762 slice 2, default disabled).
Activation still requires the installed broker ACL/identity and an
authenticated receipt subscriber. MQTT QoS1 PUBACK is never a deletion
authorization.
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


CATCH_UP_DEFAULT_WINDOW = 50
CATCH_UP_MAX_WINDOW = 500
CATCH_UP_DEFAULT_MAX_ROWS_PER_SECOND = 200.0
CATCH_UP_MAX_ROWS_PER_SECOND = 1000.0
MAX_SKIP_REASON_KEYS = 16

# publish_window(items) -> number of leading items that received a QoS 1
# PUBACK (a contiguous prefix). A PUBACK is broker acceptance only.
WindowPublisher = Callable[[list[tuple[str, str]]], int]


def _local_row_problem(
    event_id: str, payload: str, *, organization_id: str, node_id: str
) -> str | None:
    """Return a rejection reason for a corrupt local row, otherwise ``None``."""
    try:
        body = json.loads(payload, object_pairs_hook=_strict_local_pairs)
    except ReceiptProtocolError as exc:
        return str(exc) or "invalid_local_replay_payload"
    except (ValueError, TypeError):
        return "invalid_local_replay_payload"
    if (
        not isinstance(body, dict)
        or body.get("event_id") != event_id
        or body.get("node_id") != node_id
        or body.get("organization_id") not in (None, organization_id)
        or body.get("stream") not in (None, "telemetry")
        or type(body.get("node_sequence")) is not int
        or body["node_sequence"] < 1
    ):
        return "invalid_local_replay_identity"
    try:
        if str(uuid.UUID(event_id)) != event_id:
            return "invalid_local_replay_event_id"
    except (TypeError, ValueError, AttributeError):
        return "invalid_local_replay_event_id"
    return None


class CommittedReceiptCatchUp:
    """Bounded windowed FIFO catch-up resend (#1762 slice 4).

    Pending scoped rows whose first transmission is older than
    ``replay_after_seconds`` are re-published in SQLite id order, in windows.

    Bounds:

    * at most ``window`` resent rows are in flight (resent, still pending, and
      resent less than ``replay_after_seconds`` ago);
    * a token bucket caps the resend rate at ``max_rows_per_second``;
    * a sweep walks the outbox once from the head; the next sweep starts only
      ``replay_after_seconds`` after the last window of the previous one, so a
      row is never resent more often than that;
    * a window that expires with no receipt at all (central down) and a
      publish failure both back off exponentially; any applied receipt
      (``note_progress``) ends a stall backoff.

    SQLite is only read. A PUBACK never deletes a row: only an exact-row
    ``postgres_committed`` receipt prunes. Foreign-topic and corrupt local
    rows are never resent and never pruned; they are counted.
    """

    def __init__(
        self,
        queue: CommittedReceiptQueue,
        *,
        organization_id: str,
        node_id: str,
        replay_after_seconds: float,
        window: int = CATCH_UP_DEFAULT_WINDOW,
        max_rows_per_second: float = CATCH_UP_DEFAULT_MAX_ROWS_PER_SECOND,
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
        if type(window) is not int or not 1 <= window <= CATCH_UP_MAX_WINDOW:
            raise ValueError("invalid_catch_up_window")
        for value in (
            replay_after_seconds,
            max_rows_per_second,
            initial_retry_seconds,
            max_retry_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("invalid_catch_up_budget")
        if (
            max_rows_per_second > CATCH_UP_MAX_ROWS_PER_SECOND
            or max_retry_seconds < initial_retry_seconds
        ):
            raise ValueError("invalid_catch_up_budget")
        self._queue = queue
        self._organization_id = organization_id
        self._node_id = node_id
        self._topic = f"nexolab/v1/{organization_id}/{node_id}/telemetry"
        self._replay_after = float(replay_after_seconds)
        self._window = window
        self._rate = float(max_rows_per_second)
        self._initial = float(initial_retry_seconds)
        self._maximum = float(max_retry_seconds)
        self._lock = threading.Lock()
        self._tokens = float(window)
        self._token_at: float | None = None
        self._sweep_active = False
        self._sweep_cursor = 0
        self._window_floor = 0
        # (floor_exclusive, max_id, sent_at, rows_sent) of unexpired windows.
        self._windows: list[tuple[int, int, float, int]] = []
        self._last_window_at: float | None = None
        self._next_due = 0.0
        self._publish_failures = 0
        self._stalls = 0
        self._in_flight = 0
        self._resent_total = 0
        self._windows_total = 0
        self._sweeps_total = 0
        self._publish_failures_total = 0
        self._stalls_total = 0
        self._skipped: dict[str, int] = {}
        self._last_skipped: list[tuple[int, str]] = []

    # ------------------------------------------------------------ helpers
    def _backoff(self, count: int) -> float:
        return min(self._maximum, self._initial * (2 ** min(count - 1, 30)))

    def _skip(self, row_id: int, reason: str) -> None:
        key = reason if (
            reason in self._skipped or len(self._skipped) < MAX_SKIP_REASON_KEYS
        ) else "other"
        self._skipped[key] = self._skipped.get(key, 0) + 1
        self._last_skipped.append((row_id, reason))

    def note_progress(self) -> None:
        """An exact-row receipt was applied: central is reachable again."""
        with self._lock:
            if self._stalls:
                self._stalls = 0
                if self._publish_failures == 0:
                    self._next_due = 0.0

    def last_skipped(self) -> list[tuple[int, str]]:
        with self._lock:
            return list(self._last_skipped)

    def _expire_windows(self, now: float) -> None:
        while self._windows and now - self._windows[0][2] >= self._replay_after:
            floor, max_id, _sent_at, rows_sent = self._windows.pop(0)
            self._window_floor = max_id
            still_pending = self._queue.count_pending_between(floor, max_id, self._topic)
            if still_pending >= rows_sent:
                # Not one receipt came back for this window: central is
                # probably down. Back off instead of flooding the broker.
                self._stalls += 1
                self._stalls_total += 1
                self._next_due = max(self._next_due, now + self._backoff(self._stalls))
            else:
                self._stalls = 0

    # --------------------------------------------------------------- tick
    def tick(
        self,
        publish_window: WindowPublisher,
        *,
        now_monotonic: float,
        first_transmission_cursor: int,
        first_sent_at: Callable[[int], float | None],
    ) -> str:
        """Run one bounded step and return its outcome.

        ``first_transmission_cursor`` is the highest row id already sent once
        in this process; ``first_sent_at(row_id)`` returns when that row was
        first sent (monotonic), or ``None`` when unknown. Outcomes:
        ``resent``, ``retry_scheduled``, ``deferred``, ``waiting_receipt``,
        ``window_full``, ``rate_limited`` or ``skipped_rows``.
        """
        if isinstance(now_monotonic, bool) or not isinstance(
            now_monotonic, (int, float)
        ) or not math.isfinite(now_monotonic) or now_monotonic < 0:
            raise ValueError("invalid_monotonic_clock")
        if not callable(publish_window) or not callable(first_sent_at):
            raise TypeError("publisher_required")
        if type(first_transmission_cursor) is not int or first_transmission_cursor < 0:
            raise ValueError("invalid_record_cursor")
        now = float(now_monotonic)

        with self._lock:
            self._last_skipped = []
            if self._token_at is None:
                self._token_at = now
            self._tokens = min(
                float(self._window),
                self._tokens + max(0.0, now - self._token_at) * self._rate,
            )
            self._token_at = now
            self._expire_windows(now)
            if now < self._next_due:
                return "deferred"
            if not self._sweep_active:
                if (
                    self._last_window_at is not None
                    and now - self._last_window_at < self._replay_after
                ):
                    return "waiting_receipt"
                self._sweep_active = True
                self._sweep_cursor = 0
                self._window_floor = 0
                self._windows = []
                self._sweeps_total += 1

            if self._windows:
                self._in_flight = self._queue.count_pending_between(
                    self._window_floor, self._sweep_cursor, self._topic
                )
            else:
                self._in_flight = 0
            room = self._window - self._in_flight
            if room <= 0:
                return "window_full"
            budget = min(room, int(self._tokens))
            if budget < 1:
                return "rate_limited"

            limit = min(1000, budget * 4)
            rows = self._queue.receipt_catch_up_window(
                self._sweep_cursor, first_transmission_cursor, limit
            )
            # (cursor_before_row, row_id, topic, payload)
            batch: list[tuple[int, int, str, str]] = []
            scan_cursor = self._sweep_cursor
            end_reached = len(rows) < limit
            for row_id, event_id, topic, payload in rows:
                if topic != self._topic:
                    # Never resent and never pruned by a receipt; counted.
                    self._skip(row_id, "foreign_topic_row")
                    scan_cursor = row_id
                    continue
                sent_at = first_sent_at(row_id)
                if sent_at is None or now - sent_at < self._replay_after:
                    # FIFO: later rows were sent later. The sweep ends here.
                    end_reached = True
                    break
                problem = _local_row_problem(
                    event_id,
                    payload,
                    organization_id=self._organization_id,
                    node_id=self._node_id,
                )
                if problem is not None:
                    self._skip(row_id, problem)
                    scan_cursor = row_id
                    continue
                batch.append((scan_cursor, row_id, topic, payload))
                scan_cursor = row_id
                if len(batch) >= budget:
                    end_reached = False
                    break

            if not batch:
                self._sweep_cursor = max(self._sweep_cursor, scan_cursor)
                if end_reached:
                    self._sweep_active = False
                    return "waiting_receipt"
                return "skipped_rows"

        # Network I/O outside the lock; SQLite is never mutated here.
        try:
            acknowledged = int(publish_window([(t, p) for _, _, t, p in batch]))
        except (OSError, ValueError, RuntimeError, TimeoutError):
            acknowledged = 0
        acknowledged = max(0, min(acknowledged, len(batch)))

        with self._lock:
            self._tokens = max(0.0, self._tokens - len(batch))
            if acknowledged:
                previous = self._sweep_cursor
                self._sweep_cursor = batch[acknowledged - 1][1]
                self._windows.append((previous, self._sweep_cursor, now, acknowledged))
                self._last_window_at = now
                self._resent_total += acknowledged
                self._windows_total += 1
            else:
                # Skipped rows before the first unacknowledged row stay skipped.
                self._sweep_cursor = max(self._sweep_cursor, batch[0][0])
            if acknowledged < len(batch):
                self._publish_failures += 1
                self._publish_failures_total += 1
                self._next_due = now + self._backoff(self._publish_failures)
                return "retry_scheduled"
            self._publish_failures = 0
            return "resent"

    def snapshot(self, *, now_monotonic: float) -> dict[str, object]:
        if not isinstance(now_monotonic, (int, float)) or not math.isfinite(
            now_monotonic
        ):
            raise ValueError("invalid_monotonic_clock")
        with self._lock:
            return {
                "window": self._window,
                "max_rows_per_second": self._rate,
                "in_flight": self._in_flight,
                "sweep_active": self._sweep_active,
                "sweep_cursor": self._sweep_cursor,
                "sweeps_total": self._sweeps_total,
                "windows_total": self._windows_total,
                "resent_total": self._resent_total,
                "publish_failures_total": self._publish_failures_total,
                "stalls_total": self._stalls_total,
                "skipped_rows_by_reason": dict(self._skipped),
                "next_attempt_seconds": max(0.0, self._next_due - now_monotonic),
                "postgres_committed": False,
            }
