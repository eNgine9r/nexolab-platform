"""Source-only PostgreSQL receipt publisher core for Issue #1445.

This module is deliberately NOT connected to the installed MQTT runtime.
A deployment must independently verify a dedicated broker publisher identity,
enforced per-node receipt-topic ACL and receipt subscriber isolation. An
injected sender's return value is not proof of that security boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from app.db import Database, TelemetryCommittedReceipt

ReceiptSender = Callable[[str, bytes], bool]

MAX_RECEIPT_BYTES = 2048


@dataclass(frozen=True, slots=True)
class PublishAttempt:
    status: str
    event_id: str | None = None
    attempts: int = 0


class CommittedReceiptPublisher:
    """Crash-recoverable, bounded one-intent-at-a-time send loop.

    send_acknowledged must return True ONLY after a real QoS1 broker PUBACK
    from an independently authorized dedicated central publishing identity.
    A broker PUBACK still does not establish delivery to the Edge subscriber.
    """

    def __init__(
        self,
        database: Database,
        sender: ReceiptSender,
        *,
        initial_retry_seconds: float = 2.0,
        max_retry_seconds: float = 300.0,
        max_payload_bytes: int = MAX_RECEIPT_BYTES,
    ) -> None:
        if database.engine.dialect.name != "postgresql":
            raise RuntimeError("postgresql_required_for_committed_receipt")
        if (
            initial_retry_seconds <= 0
            or max_retry_seconds < initial_retry_seconds
            or max_payload_bytes < 1
            or max_payload_bytes > MAX_RECEIPT_BYTES
        ):
            raise ValueError("invalid_receipt_publisher_policy")
        if not callable(sender):
            raise TypeError("receipt_sender_required")
        self._database = database
        self._sender = sender
        self._initial_retry_seconds = initial_retry_seconds
        self._max_retry_seconds = max_retry_seconds
        self._max_payload_bytes = max_payload_bytes

    def run_once(self, *, now: datetime | None = None) -> PublishAttempt:
        observed = now or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("receipt_clock_must_be_aware")
        table = TelemetryCommittedReceipt.__table__
        with self._database.engine.begin() as connection:
            record = connection.execute(
                select(table)
                .where(
                    table.c.published_at.is_(None),
                    or_(
                        table.c.next_attempt_at.is_(None),
                        table.c.next_attempt_at <= observed,
                    ),
                )
                .order_by(table.c.committed_at, table.c.event_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).mappings().first()
            if record is None:
                return PublishAttempt("idle")
            event_id = str(record["event_id"])
            attempts = int(record["attempts"]) + 1
            retry_delay = min(
                self._max_retry_seconds,
                self._initial_retry_seconds * (2 ** min(attempts - 1, 16)),
            )
            connection.execute(
                update(table)
                .where(table.c.event_id == event_id)
                .values(
                    attempts=attempts,
                    next_attempt_at=observed + timedelta(seconds=retry_delay),
                )
            )
            topic = str(record["topic"])
            payload = record["payload"]
            receipt_id = str(record["receipt_id"])

            # The Edge validator refuses receipts older than seven days.
            # Reissue a fresh receipt (not a fresh sample commit) from the
            # durable PostgreSQL row before an aged retry is published.
            stamp = payload.get("accepted_at")
            if not isinstance(stamp, str):
                return PublishAttempt("retry", event_id, attempts)
            try:
                accepted_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                return PublishAttempt("retry", event_id, attempts)
            if accepted_at.tzinfo is None or accepted_at.utcoffset() is None:
                return PublishAttempt("retry", event_id, attempts)
            if accepted_at <= observed - timedelta(days=6):
                receipt_id = str(uuid4())
                payload = dict(payload)
                payload["receipt_id"] = receipt_id
                payload["accepted_at"] = observed.astimezone(UTC).isoformat().replace(
                    "+00:00", "Z"
                )
                connection.execute(
                    update(table)
                    .where(table.c.event_id == event_id)
                    .values(receipt_id=receipt_id, payload=payload)
                )

        try:
            body = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            if not (0 < len(body) <= self._max_payload_bytes):
                return PublishAttempt("retry", event_id, attempts)
            confirmed = self._sender(topic, body)
        except Exception:  # noqa: BLE001 - transport remains retryable
            confirmed = False
        if confirmed is not True:
            return PublishAttempt("retry", event_id, attempts)

        # This mark follows the callback's broker ACK, NEVER precedes it.
        # If the worker crashes here, the durable lease expires and retry
        # may redeliver the same receipt; receiver must dedupe receipt_id.
        with self._database.engine.begin() as connection:
            changed = connection.execute(
                update(table)
                .where(
                    table.c.event_id == event_id,
                    table.c.attempts == attempts,
                    table.c.receipt_id == receipt_id,
                    table.c.published_at.is_(None),
                )
                .values(published_at=observed)
            ).rowcount
        return PublishAttempt(
            "published" if changed == 1 else "retry", event_id, attempts
        )

    def pending_stats(self, *, now: datetime | None = None) -> dict[str, float | int | None]:
        observed = now or datetime.now(UTC)
        table = TelemetryCommittedReceipt.__table__
        with self._database.engine.connect() as connection:
            size, oldest = connection.execute(
                select(func.count(), func.min(table.c.committed_at))
                .where(table.c.published_at.is_(None))
            ).one()
        age = (observed - oldest).total_seconds() if oldest is not None else None
        return {"pending": int(size), "oldest_pending_age_seconds": age}
