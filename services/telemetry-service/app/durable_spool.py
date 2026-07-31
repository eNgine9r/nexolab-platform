from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock


class DurableSpoolError(RuntimeError):
    """Base error for local durable ingestion spool operations."""


class DurableSpoolCapacityError(DurableSpoolError):
    """The configured record or byte capacity would be exceeded."""


@dataclass(frozen=True, slots=True)
class SpoolAppendResult:
    record_id: int
    duplicate: bool


@dataclass(frozen=True, slots=True)
class SpoolRecord:
    record_id: int
    work_type: str
    event_id: str | None
    delivery_key: str | None
    payload: bytes
    topic: str | None
    received_at: datetime
    payload_size: int
    payload_truncated: bool
    reason_code: str | None
    reason_detail: str | None
    created_at: datetime
    attempts: int


@dataclass(frozen=True, slots=True)
class SpoolStats:
    pending_records: int
    terminal_records: int
    payload_bytes: int
    oldest_pending_at: datetime | None
    max_record_id: int

    @property
    def total_records(self) -> int:
        return self.pending_records + self.terminal_records

    @property
    def oldest_pending_age_seconds(self) -> float | None:
        if self.oldest_pending_at is None:
            return None
        return max(
            0.0,
            (datetime.now(UTC) - self.oldest_pending_at).total_seconds(),
        )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class DurableIngestionSpool:
    """SQLite WAL spool that owns ingestion work until persistence succeeds."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        max_records: int,
        max_bytes: int,
        busy_timeout_seconds: float = 5.0,
    ) -> None:
        if max_records < 1:
            raise ValueError("spool max_records must be positive")
        if max_bytes < 1:
            raise ValueError("spool max_bytes must be positive")
        if busy_timeout_seconds <= 0:
            raise ValueError("spool busy timeout must be positive")

        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_records = max_records
        self.max_bytes = max_bytes
        self._lock = Lock()
        try:
            self._connection = sqlite3.connect(
                self.path,
                check_same_thread=False,
                timeout=busy_timeout_seconds,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute(
                f"PRAGMA busy_timeout = {int(busy_timeout_seconds * 1000)}"
            )
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema()
        except (OSError, sqlite3.Error) as exc:
            raise DurableSpoolError(
                f"failed to initialize ingestion spool: {exc}"
            ) from exc

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_spool (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'terminal')),
                    work_type TEXT NOT NULL
                        CHECK(work_type IN ('telemetry', 'dead_letter')),
                    event_id TEXT,
                    delivery_key TEXT,
                    payload BLOB NOT NULL,
                    topic TEXT,
                    received_at TEXT NOT NULL,
                    payload_size INTEGER NOT NULL CHECK(payload_size >= 0),
                    payload_truncated INTEGER NOT NULL
                        CHECK(payload_truncated IN (0, 1)),
                    reason_code TEXT,
                    reason_detail TEXT,
                    created_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                    last_error TEXT,
                    last_attempt_at TEXT,
                    terminal_at TEXT,
                    CHECK(
                        (work_type = 'telemetry'
                            AND event_id IS NOT NULL
                            AND reason_code IS NULL)
                        OR
                        (work_type = 'dead_letter'
                            AND event_id IS NULL
                            AND reason_code IS NOT NULL)
                    )
                )
                """
            )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_spool_event_id
                ON ingestion_spool(event_id)
                WHERE event_id IS NOT NULL
                """
            )
            self._connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_spool_delivery_key
                ON ingestion_spool(delivery_key)
                WHERE delivery_key IS NOT NULL
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_ingestion_spool_pending_order
                ON ingestion_spool(status, id)
                """
            )

    def append_telemetry(
        self,
        *,
        event_id: str,
        payload: bytes,
        topic: str | None,
        received_at: datetime,
        delivery_key: str | None = None,
    ) -> SpoolAppendResult:
        normalized_event_id = event_id.strip()
        if not normalized_event_id:
            raise ValueError("event_id is required")
        return self._append(
            work_type="telemetry",
            event_id=normalized_event_id,
            delivery_key=self._normalize_delivery_key(delivery_key),
            payload=payload,
            topic=topic,
            received_at=received_at,
            payload_size=len(payload),
            payload_truncated=False,
            reason_code=None,
            reason_detail=None,
        )

    def append_dead_letter(
        self,
        *,
        payload: bytes,
        payload_size: int,
        payload_truncated: bool,
        reason_code: str,
        reason_detail: str,
        topic: str | None,
        received_at: datetime,
        delivery_key: str | None = None,
    ) -> SpoolAppendResult:
        if payload_size < len(payload):
            raise ValueError("payload_size cannot be smaller than retained payload")
        normalized_reason = reason_code.strip()
        if not normalized_reason:
            raise ValueError("reason_code is required")
        return self._append(
            work_type="dead_letter",
            event_id=None,
            delivery_key=self._normalize_delivery_key(delivery_key),
            payload=payload,
            topic=topic,
            received_at=received_at,
            payload_size=payload_size,
            payload_truncated=payload_truncated,
            reason_code=normalized_reason,
            reason_detail=reason_detail,
        )

    @staticmethod
    def _normalize_delivery_key(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    def _append(
        self,
        *,
        work_type: str,
        event_id: str | None,
        delivery_key: str | None,
        payload: bytes,
        topic: str | None,
        received_at: datetime,
        payload_size: int,
        payload_truncated: bool,
        reason_code: str | None,
        reason_detail: str | None,
    ) -> SpoolAppendResult:
        normalized_received_at = received_at.astimezone(UTC).isoformat()
        created_at = datetime.now(UTC).isoformat()
        retained_size = len(payload)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._find_existing(
                    event_id=event_id,
                    delivery_key=delivery_key,
                )
                if existing is not None:
                    self._connection.commit()
                    return SpoolAppendResult(
                        record_id=int(existing["id"]),
                        duplicate=True,
                    )

                stats = self._connection.execute(
                    """
                    SELECT COUNT(*) AS records,
                           COALESCE(SUM(LENGTH(payload)), 0) AS payload_bytes
                    FROM ingestion_spool
                    """
                ).fetchone()
                records = int(stats["records"])
                payload_bytes = int(stats["payload_bytes"])
                if records >= self.max_records:
                    raise DurableSpoolCapacityError(
                        f"ingestion spool record capacity {self.max_records} reached"
                    )
                if payload_bytes + retained_size > self.max_bytes:
                    raise DurableSpoolCapacityError(
                        f"ingestion spool byte capacity {self.max_bytes} would be exceeded"
                    )

                cursor = self._connection.execute(
                    """
                    INSERT INTO ingestion_spool(
                        work_type,
                        event_id,
                        delivery_key,
                        payload,
                        topic,
                        received_at,
                        payload_size,
                        payload_truncated,
                        reason_code,
                        reason_detail,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        work_type,
                        event_id,
                        delivery_key,
                        sqlite3.Binary(payload),
                        topic,
                        normalized_received_at,
                        payload_size,
                        int(payload_truncated),
                        reason_code,
                        reason_detail,
                        created_at,
                    ),
                )
                record_id = int(cursor.lastrowid)
                self._connection.commit()
                return SpoolAppendResult(record_id=record_id, duplicate=False)
            except DurableSpoolCapacityError:
                self._connection.rollback()
                raise
            except sqlite3.IntegrityError:
                self._connection.rollback()
                existing = self._find_existing(
                    event_id=event_id,
                    delivery_key=delivery_key,
                )
                if existing is not None:
                    return SpoolAppendResult(
                        record_id=int(existing["id"]),
                        duplicate=True,
                    )
                raise DurableSpoolError("ingestion spool uniqueness conflict")
            except sqlite3.Error as exc:
                self._connection.rollback()
                raise DurableSpoolError(
                    f"failed to append ingestion work: {exc}"
                ) from exc

    def _find_existing(
        self,
        *,
        event_id: str | None,
        delivery_key: str | None,
    ) -> sqlite3.Row | None:
        clauses: list[str] = []
        values: list[str] = []
        if event_id is not None:
            clauses.append("event_id = ?")
            values.append(event_id)
        if delivery_key is not None:
            clauses.append("delivery_key = ?")
            values.append(delivery_key)
        if not clauses:
            return None
        return self._connection.execute(
            "SELECT id FROM ingestion_spool WHERE " + " OR ".join(clauses) + " LIMIT 1",
            tuple(values),
        ).fetchone()

    def oldest_pending(self) -> SpoolRecord | None:
        with self._lock:
            try:
                row = self._connection.execute(
                    """
                    SELECT *
                    FROM ingestion_spool
                    WHERE status = 'pending'
                    ORDER BY id
                    LIMIT 1
                    """
                ).fetchone()
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to read ingestion spool: {exc}"
                ) from exc
        if row is None:
            return None
        return SpoolRecord(
            record_id=int(row["id"]),
            work_type=str(row["work_type"]),
            event_id=(str(row["event_id"]) if row["event_id"] is not None else None),
            delivery_key=(
                str(row["delivery_key"])
                if row["delivery_key"] is not None
                else None
            ),
            payload=bytes(row["payload"]),
            topic=str(row["topic"]) if row["topic"] is not None else None,
            received_at=_parse_datetime(str(row["received_at"])),
            payload_size=int(row["payload_size"]),
            payload_truncated=bool(row["payload_truncated"]),
            reason_code=(
                str(row["reason_code"])
                if row["reason_code"] is not None
                else None
            ),
            reason_detail=(
                str(row["reason_detail"])
                if row["reason_detail"] is not None
                else None
            ),
            created_at=_parse_datetime(str(row["created_at"])),
            attempts=int(row["attempts"]),
        )

    def delete(self, record_id: int) -> None:
        with self._lock:
            try:
                with self._connection:
                    self._connection.execute(
                        "DELETE FROM ingestion_spool WHERE id = ?",
                        (record_id,),
                    )
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to delete ingestion spool record {record_id}: {exc}"
                ) from exc

    def mark_attempt(self, record_id: int, error: str) -> None:
        with self._lock:
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        UPDATE ingestion_spool
                        SET attempts = attempts + 1,
                            last_error = ?,
                            last_attempt_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (error[:4096], datetime.now(UTC).isoformat(), record_id),
                    )
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to update ingestion spool record {record_id}: {exc}"
                ) from exc

    def mark_terminal(self, record_id: int, error: str) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            try:
                with self._connection:
                    self._connection.execute(
                        """
                        UPDATE ingestion_spool
                        SET status = 'terminal',
                            attempts = attempts + 1,
                            last_error = ?,
                            last_attempt_at = ?,
                            terminal_at = ?
                        WHERE id = ? AND status = 'pending'
                        """,
                        (error[:4096], now, now, record_id),
                    )
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to quarantine ingestion spool record {record_id}: {exc}"
                ) from exc

    def stats(self) -> SpoolStats:
        with self._lock:
            try:
                row = self._connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END)
                            AS pending_records,
                        SUM(CASE WHEN status = 'terminal' THEN 1 ELSE 0 END)
                            AS terminal_records,
                        COALESCE(SUM(LENGTH(payload)), 0) AS payload_bytes,
                        MIN(CASE WHEN status = 'pending' THEN created_at END)
                            AS oldest_pending_at,
                        COALESCE(MAX(id), 0) AS max_record_id
                    FROM ingestion_spool
                    """
                ).fetchone()
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to inspect ingestion spool: {exc}"
                ) from exc
        oldest = row["oldest_pending_at"]
        return SpoolStats(
            pending_records=int(row["pending_records"] or 0),
            terminal_records=int(row["terminal_records"] or 0),
            payload_bytes=int(row["payload_bytes"]),
            oldest_pending_at=(
                _parse_datetime(str(oldest)) if oldest is not None else None
            ),
            max_record_id=int(row["max_record_id"]),
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except sqlite3.Error as exc:
                raise DurableSpoolError(
                    f"failed to close ingestion spool: {exc}"
                ) from exc
