"""Default-OFF runtime wiring for PostgreSQL-committed receipts (#1762 slice 1).

Only constructed when ``NEXOLAB_COMMITTED_RECEIPTS=enabled``. With the flag
disabled the ingestion worker never calls into this module.

Boundaries this module keeps:

* the ingestion worker never waits on MQTT: the receipt publisher runs in its
  own thread and only reads the durable ``telemetry_committed_receipts``
  outbox written in the telemetry transaction;
* a failing publisher never changes telemetry readiness; it is reported as a
  separate subsystem;
* the publisher identity comes from settings and a mounted password file,
  never from a telemetry payload.

A broker PUBACK proves broker acceptance only. Edge delivery, the installed
broker ACL (#1450) and site activation (#1428, #1449) remain separate gates.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any, Callable, Protocol

from app.committed_receipt_publisher import CommittedReceiptPublisher, PublishAttempt
from app.contracts import TelemetryEvent
from app.nodes.domain import NodeTopicStream, parse_node_topic

LOGGER = logging.getLogger("nexolab.telemetry.committed_receipts")

# Deterministic identity conflicts raised by Database.persist/receipt identity.
# Retrying them can never succeed, so the ingestion worker dead-letters them
# instead of blocking the queue head.
RECEIPT_CONFLICT_ERRORS = frozenset(
    {
        "invalid_receipt_organization",
        "noncanonical_receipt_organization",
        "invalid_receipt_node",
        "invalid_receipt_sequence",
        "receipt_node_mismatch",
        "receipt_sequence_unverified",
        "receipt_organization_mismatch",
        "receipt_duplicate_event_identity_conflict",
        "receipt_outbox_identity_conflict",
    }
)
RECEIPT_OUTBOX_FULL_ERROR = "receipt_outbox_capacity_reached"
RECEIPT_CONFLICT_REASON = "committed_receipt_conflict"

CommittedPersist = Callable[
    [TelemetryEvent, dict[str, Any], str | None, datetime],
    tuple[bool, str, str, bool | None],
]


class CommittedReceiptStats:
    """Thread-safe counters shared by the ingestion worker and publisher loop."""

    _COUNTERS = (
        "committed_ingress_total",
        "conflict_dead_letter_total",
        "outbox_full_fallback_total",
        "publish_attempts_total",
        "published_total",
        "publish_failures_total",
        "loop_errors_total",
    )

    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[str, Any] = {name: 0 for name in self._COUNTERS}
        self._values.update(
            pending=None,
            oldest_pending_age_seconds=None,
            consecutive_failures=0,
            last_published_at=None,
            last_error=None,
            stats_error=None,
            publisher_running=False,
            transport_connected=None,
        )

    def increment(self, name: str, value: int = 1) -> None:
        if name not in self._COUNTERS:
            raise KeyError(name)
        with self._lock:
            self._values[name] += value

    def update(self, **values: Any) -> None:
        with self._lock:
            for name, value in values.items():
                if name not in self._values or name in self._COUNTERS:
                    raise KeyError(name)
                self._values[name] = value

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            values = dict(self._values)
        if not values["publisher_running"]:
            status = "stopped"
        elif values["consecutive_failures"] or values["stats_error"]:
            status = "degraded"
        else:
            status = "ready"
        values["status"] = status
        values["mode"] = "enabled"
        return values


class CommittedReceiptIngress:
    """Selects the committed path for org-scoped node telemetry topics only."""

    def __init__(
        self,
        persist: CommittedPersist,
        stats: CommittedReceiptStats,
        *,
        on_committed: Callable[[], None] | None = None,
    ) -> None:
        if not callable(persist):
            raise TypeError("committed_persist_required")
        if on_committed is not None and not callable(on_committed):
            raise TypeError("committed_notifier_must_be_callable")
        self._persist = persist
        self.stats = stats
        self._on_committed = on_committed

    def set_commit_notifier(self, on_committed: Callable[[], None] | None) -> None:
        if on_committed is not None and not callable(on_committed):
            raise TypeError("committed_notifier_must_be_callable")
        self._on_committed = on_committed

    @staticmethod
    def applies_to(topic: str | None) -> bool:
        if topic is None:
            return False
        try:
            parsed = parse_node_topic(topic)
        except ValueError:
            return False
        return parsed.stream is NodeTopicStream.TELEMETRY

    def persist(
        self,
        event: TelemetryEvent,
        raw: dict[str, Any],
        topic: str | None,
        observed_at: datetime,
    ) -> tuple[bool, str, str, bool | None]:
        self.stats.increment("committed_ingress_total")
        result = self._persist(event, raw, topic, observed_at)
        # The telemetry row and its receipt intent are committed when persist
        # returns. Wake the publisher now instead of waiting for its idle poll.
        notifier = self._on_committed
        if result[0] and notifier is not None:
            try:
                notifier()
            except Exception:  # noqa: BLE001 - a wake hint never fails ingestion
                LOGGER.warning("Committed receipt publisher wake failed", exc_info=True)
        return result


class ReceiptTransport(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class ReceiptPublisherCore(Protocol):
    def run_once(self, *, now: datetime | None = None) -> PublishAttempt: ...

    # Optional: ``run_batch(*, limit, now=None) -> list[PublishAttempt]``.

    def pending_stats(
        self, *, now: datetime | None = None
    ) -> dict[str, float | int | None]: ...


class CommittedReceiptPublisherLoop:
    """Bounded background loop around CommittedReceiptPublisher.

    Each iteration publishes one bounded batch (``run_batch``, or one intent
    with ``run_once``). An idle loop sleeps ``idle_seconds`` but wakes at once
    when the ingestion path commits a new intent (``wake``). A failed send or
    database error waits with a bounded exponential backoff and is not
    shortened by wakes. Per-row retry leases stay in PostgreSQL, so a restart
    resumes from the durable outbox.
    """

    def __init__(
        self,
        publisher: ReceiptPublisherCore,
        stats: CommittedReceiptStats,
        *,
        transport: ReceiptTransport | None = None,
        connected: Callable[[], bool] | None = None,
        idle_seconds: float = 1.0,
        retry_initial_seconds: float = 2.0,
        retry_max_seconds: float = 300.0,
        stats_interval_seconds: float = 5.0,
        stop_timeout_seconds: float = 10.0,
        batch_size: int = 50,
    ) -> None:
        if (
            type(batch_size) is not int
            or not 1 <= batch_size <= 500
            or idle_seconds <= 0
            or retry_initial_seconds <= 0
            or retry_max_seconds < retry_initial_seconds
            or stats_interval_seconds <= 0
            or stop_timeout_seconds <= 0
        ):
            raise ValueError("invalid_receipt_loop_policy")
        self._publisher = publisher
        self._stats = stats
        self._transport = transport
        self._connected = connected
        self._idle_seconds = idle_seconds
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._stats_interval_seconds = stats_interval_seconds
        self._stop_timeout_seconds = stop_timeout_seconds
        self._batch_size = batch_size
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None
        self._next_stats_at = 0.0

    def wake(self) -> None:
        """Hint that a new receipt intent was committed. Never blocks."""
        self._wake.set()

    @property
    def stats(self) -> CommittedReceiptStats:
        return self._stats

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("receipt_publisher_loop_already_started")
        self._stop.clear()
        if self._transport is not None:
            try:
                self._transport.start()
            except Exception as exc:  # noqa: BLE001 - never block service start
                self._stats.increment("loop_errors_total")
                self._stats.update(last_error=type(exc).__name__)
                LOGGER.error(
                    "Committed receipt transport failed to start: %s",
                    type(exc).__name__,
                )
        self._thread = Thread(
            target=self._run,
            name="committed-receipt-publisher",
            daemon=True,
        )
        self._stats.update(publisher_running=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=self._stop_timeout_seconds)
            if thread.is_alive():
                LOGGER.error("Committed receipt publisher did not stop in time")
        self._thread = None
        self._stats.update(publisher_running=False)
        if self._transport is not None:
            try:
                self._transport.stop()
            except Exception as exc:  # noqa: BLE001 - shutdown is best effort
                LOGGER.warning(
                    "Committed receipt transport stop failed: %s",
                    type(exc).__name__,
                )

    def run_iteration(self, retry_delay: float) -> tuple[str, float]:
        """Run one bounded step; return the outcome and the next delay.

        Exposed for deterministic tests; the thread calls it in a loop.
        """
        self._refresh_stats()
        try:
            run_batch = getattr(self._publisher, "run_batch", None)
            if callable(run_batch):
                attempts = list(run_batch(limit=self._batch_size))
            else:
                attempts = [self._publisher.run_once()]
                if attempts[0].status == "idle":
                    attempts = []
        except Exception as exc:  # noqa: BLE001 - DB outage keeps retrying
            failures = self._stats.snapshot()["consecutive_failures"] + 1
            self._stats.increment("loop_errors_total")
            self._stats.update(
                consecutive_failures=failures,
                last_error=type(exc).__name__,
            )
            LOGGER.warning(
                "Committed receipt publisher step failed (%s); retrying in %.2fs",
                type(exc).__name__,
                retry_delay,
            )
            return "error", retry_delay
        if not attempts:
            self._stats.update(consecutive_failures=0)
            return "idle", self._idle_seconds
        published = sum(1 for attempt in attempts if attempt.status == "published")
        self._stats.increment("publish_attempts_total", len(attempts))
        if published:
            self._stats.increment("published_total", published)
        if len(attempts) - published:
            self._stats.increment("publish_failures_total", len(attempts) - published)
        if published:
            # Partial failures keep their own durable per-row retry lease.
            self._stats.update(
                consecutive_failures=0,
                last_published_at=datetime.now(UTC).isoformat(),
                last_error=None if published == len(attempts) else "publish_not_acknowledged",
            )
            return "published", 0.0
        failures = self._stats.snapshot()["consecutive_failures"] + 1
        self._stats.update(
            consecutive_failures=failures,
            last_error="publish_not_acknowledged",
        )
        return "retry", retry_delay

    def _run(self) -> None:
        retry_delay = self._retry_initial_seconds
        while not self._stop.is_set():
            # Clear before the step so a commit during the step is not lost.
            self._wake.clear()
            outcome, delay = self.run_iteration(retry_delay)
            if outcome in {"error", "retry"}:
                retry_delay = min(retry_delay * 2, self._retry_max_seconds)
                # Backoff is never shortened by commit wakes.
                self._stop.wait(delay)
                continue
            retry_delay = self._retry_initial_seconds
            if delay > 0:
                self._wake.wait(delay)

    def _refresh_stats(self) -> None:
        if self._connected is not None:
            try:
                self._stats.update(transport_connected=bool(self._connected()))
            except Exception:  # noqa: BLE001 - diagnostics only
                self._stats.update(transport_connected=False)
        now = monotonic()
        if now < self._next_stats_at:
            return
        self._next_stats_at = now + self._stats_interval_seconds
        try:
            pending = self._publisher.pending_stats()
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            self._stats.update(stats_error=type(exc).__name__)
            return
        self._stats.update(
            pending=pending.get("pending"),
            oldest_pending_age_seconds=pending.get("oldest_pending_age_seconds"),
            stats_error=None,
        )


def build_committed_receipt_runtime(
    settings: Any,
    database: Any,
    authorizer: Any,
    *,
    mqtt_module: Any | None = None,
) -> tuple[CommittedReceiptIngress, CommittedReceiptPublisherLoop]:
    """Fail-closed construction from validated settings (startup only)."""
    from app.committed_receipt_mqtt import CommittedReceiptMqttSender
    from app.mqtt_tls import MQTTTLSConfig

    if not settings.committed_receipts_enabled:
        raise RuntimeError("committed_receipts_disabled")
    if authorizer is None:
        raise RuntimeError("committed_receipts_require_node_registry")
    if database.engine.dialect.name != "postgresql":
        raise RuntimeError("postgresql_required_for_committed_receipt")
    # Server-authenticated TLS only: a shared client certificate could map the
    # publisher onto the ingestion identity (use_identity_as_username).
    tls_config = replace(
        MQTTTLSConfig.from_settings(settings),
        client_certificate_file=None,
        client_key_file=None,
    )
    sender = CommittedReceiptMqttSender(
        host=settings.mqtt_host,
        port=settings.mqtt_port,
        client_id=settings.nexolab_receipt_publisher_client_id,
        username=settings.nexolab_receipt_publisher_username or "",
        password_file=settings.nexolab_receipt_publisher_password_file or "",
        tls_config=tls_config,
        mqtt_module=mqtt_module,
    )
    publisher = CommittedReceiptPublisher(
        database,
        sender,
        initial_retry_seconds=settings.nexolab_receipt_publisher_retry_initial_seconds,
        max_retry_seconds=settings.nexolab_receipt_publisher_retry_max_seconds,
    )
    stats = CommittedReceiptStats()
    loop = CommittedReceiptPublisherLoop(
        publisher,
        stats,
        transport=sender,
        connected=lambda: sender.connected,
        idle_seconds=settings.nexolab_receipt_publisher_idle_seconds,
        retry_initial_seconds=settings.nexolab_receipt_publisher_retry_initial_seconds,
        retry_max_seconds=settings.nexolab_receipt_publisher_retry_max_seconds,
        batch_size=settings.nexolab_receipt_publisher_batch_size,
    )
    ingress = CommittedReceiptIngress(
        authorizer.authorize_and_persist_committed,
        stats,
        on_committed=loop.wake,
    )
    return ingress, loop
