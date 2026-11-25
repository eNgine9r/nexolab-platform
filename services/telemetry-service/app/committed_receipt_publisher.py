"""Source-only PostgreSQL receipt publisher core for Issue #1445.

Runtime use is limited to the default-OFF NEXOLAB_COMMITTED_RECEIPTS flag
(#1762, app/committed_receipt_runtime.py).
A deployment must independently verify a dedicated broker publisher identity,
enforced per-node receipt-topic ACL and receipt subscriber isolation. An
injected sender's return value is not proof of that security boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Callable, Sequence
from uuid import uuid4

from sqlalchemy import func, or_, select, update

from app.db import Database, TelemetryCommittedReceipt

ReceiptSender = Callable[[str, bytes], bool]

MAX_RECEIPT_BYTES = 2048
MAX_RECEIPT_BATCH = 500


@dataclass(frozen=True, slots=True)
class PublishAttempt:
    status: str
    event_id: str | None = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class _Claim:
    event_id: str
    attempts: int
    receipt_id: str
    topic: str
    body: bytes | None


class CommittedReceiptPublisher:
    """Crash-recoverable, bounded batch receipt publisher.

    send_acknowledged must return True ONLY after a real QoS1 broker PUBACK
    from an independently authorized dedicated central publishing identity.
    A broker PUBACK still does not establish delivery to the Edge subscriber.

    #1762 slice 4: the Edge binds each receipt to its exact pending row, so a
    receipt no longer waits for older receipts of the same node. Intents are
    claimed in commit order, in bounded batches, each with its own durable
    retry lease. A sender that exposes ``send_batch(items) -> list[bool]``
    publishes a batch with per-message QoS1 PUBACK tracking.
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
        """Claim and publish at most one intent (kept for single-step use)."""
        attempts = self.run_batch(limit=1, now=now)
        return attempts[0] if attempts else PublishAttempt("idle")

    def run_batch(
        self, *, limit: int = 50, now: datetime | None = None
    ) -> list[PublishAttempt]:
        """Claim up to ``limit`` due intents, publish them, mark the PUBACKed.

        Returns one PublishAttempt per claimed intent (empty when idle). Each
        claim first takes a durable retry lease in its own committed
        transaction; ``published_at`` is set only after that intent's PUBACK.
        """
        if type(limit) is not int or not 1 <= limit <= MAX_RECEIPT_BATCH:
            raise ValueError("invalid_receipt_batch_limit")
        observed = now or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("receipt_clock_must_be_aware")
        claims = self._claim(observed, limit)
        if not claims:
            return []

        results: dict[str, bool] = {}
        sendable = [claim for claim in claims if claim.body is not None]
        if sendable:
            confirmations = self._send(
                [(claim.topic, claim.body) for claim in sendable]  # type: ignore[misc]
            )
            for claim, confirmed in zip(sendable, confirmations):
                results[claim.event_id] = confirmed is True

        acknowledged = [claim for claim in sendable if results.get(claim.event_id)]
        published: set[str] = set()
        if acknowledged:
            table = TelemetryCommittedReceipt.__table__
            # This mark follows each broker ACK, NEVER precedes it. If the
            # worker crashes here, the durable lease expires and retry may
            # redeliver the same receipt; the Edge dedupes receipt_id.
            with self._database.engine.begin() as connection:
                for claim in acknowledged:
                    changed = connection.execute(
                        update(table)
                        .where(
                            table.c.event_id == claim.event_id,
                            table.c.attempts == claim.attempts,
                            table.c.receipt_id == claim.receipt_id,
                            table.c.published_at.is_(None),
                        )
                        .values(published_at=observed)
                    ).rowcount
                    if changed == 1:
                        published.add(claim.event_id)
        return [
            PublishAttempt(
                "published" if claim.event_id in published else "retry",
                claim.event_id,
                claim.attempts,
            )
            for claim in claims
        ]

    def _send(self, items: list[tuple[str, bytes]]) -> list[bool]:
        batch_sender: Any = getattr(self._sender, "send_batch", None)
        if callable(batch_sender):
            try:
                confirmations = list(batch_sender(items))
            except Exception:  # noqa: BLE001 - transport remains retryable
                return [False] * len(items)
            if len(confirmations) != len(items):
                return [False] * len(items)
            return [value is True for value in confirmations]
        results = []
        for topic, body in items:
            try:
                confirmed = self._sender(topic, body)
            except Exception:  # noqa: BLE001 - transport remains retryable
                confirmed = False
            results.append(confirmed is True)
        return results

    def _claim(self, observed: datetime, limit: int) -> list[_Claim]:
        table = TelemetryCommittedReceipt.__table__
        claims: list[_Claim] = []
        with self._database.engine.begin() as connection:
            records: Sequence[Any] = connection.execute(
                select(table)
                .where(
                    table.c.published_at.is_(None),
                    or_(
                        table.c.next_attempt_at.is_(None),
                        table.c.next_attempt_at <= observed,
                    ),
                )
                .order_by(table.c.committed_at, table.c.event_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).mappings().all()
            for record in records:
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
                body: bytes | None = None
                stamp = payload.get("accepted_at")
                accepted_at: datetime | None = None
                if isinstance(stamp, str):
                    try:
                        accepted_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    except ValueError:
                        accepted_at = None
                if accepted_at is not None and (
                    accepted_at.tzinfo is None or accepted_at.utcoffset() is None
                ):
                    accepted_at = None
                if accepted_at is not None:
                    if accepted_at <= observed - timedelta(days=6):
                        receipt_id = str(uuid4())
                        payload = dict(payload)
                        payload["receipt_id"] = receipt_id
                        payload["accepted_at"] = (
                            observed.astimezone(UTC).isoformat().replace("+00:00", "Z")
                        )
                        connection.execute(
                            update(table)
                            .where(table.c.event_id == event_id)
                            .values(receipt_id=receipt_id, payload=payload)
                        )
                    try:
                        encoded = json.dumps(
                            payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    except (TypeError, ValueError):
                        encoded = b""
                    if 0 < len(encoded) <= self._max_payload_bytes:
                        body = encoded
                claims.append(_Claim(event_id, attempts, receipt_id, topic, body))
        return claims

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
