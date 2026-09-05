from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3

from app.domain import DeliveryState, RenderedMessage, ReportSnapshot


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    id: int
    snapshot_id: str
    snapshot_sha256: str
    destination_chat_id: str
    destination_message_thread_id: int | None
    text: str
    button_url: str
    state: DeliveryState
    attempts: int
    available_at: datetime
    locked_at: datetime | None
    last_attempt_at: datetime | None
    last_error_code: str | None
    telegram_message_id: int | None
    sent_at: datetime | None
    duplicate_risk: bool


class DeliveryOutboxError(RuntimeError):
    pass


class DeliveryOutbox:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path.parent.chmod(0o700)
        self._initialize()
        self._path.chmod(0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'telegram_deliveries'"
            ).fetchone()
            if exists is None:
                self._create_delivery_table(connection)
            else:
                columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(telegram_deliveries)")}
                if "destination_message_thread_id" not in columns:
                    self._migrate_legacy_destination_identity(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS ix_telegram_deliveries_ready
                ON telegram_deliveries(state, available_at, id)
                """
            )

    @staticmethod
    def _create_delivery_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL,
                snapshot_sha256 TEXT NOT NULL,
                destination_chat_id TEXT NOT NULL,
                destination_message_thread_id INTEGER NOT NULL DEFAULT 0,
                rendered_text TEXT NOT NULL,
                button_url TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                available_at TEXT NOT NULL,
                locked_at TEXT,
                last_attempt_at TEXT,
                last_error_code TEXT,
                telegram_message_id INTEGER,
                sent_at TEXT,
                duplicate_risk INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(snapshot_id, destination_chat_id, destination_message_thread_id),
                CHECK(destination_message_thread_id >= 0),
                CHECK(state IN ('pending','sending','sent','retry_wait','failed')),
                CHECK(attempts >= 0),
                CHECK(duplicate_risk IN (0,1))
            )
            """
        )

    @classmethod
    def _migrate_legacy_destination_identity(cls, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        try:
            before = int(connection.execute("SELECT COUNT(*) FROM telegram_deliveries").fetchone()[0])
            connection.execute("ALTER TABLE telegram_deliveries RENAME TO telegram_deliveries_legacy")
            cls._create_delivery_table(connection)
            connection.execute(
                """
                INSERT INTO telegram_deliveries (
                    id, snapshot_id, snapshot_sha256, destination_chat_id,
                    destination_message_thread_id, rendered_text, button_url, state, attempts,
                    available_at, locked_at, last_attempt_at, last_error_code,
                    telegram_message_id, sent_at, duplicate_risk, created_at, updated_at
                )
                SELECT
                    id, snapshot_id, snapshot_sha256, destination_chat_id,
                    0, rendered_text, button_url, state, attempts,
                    available_at, locked_at, last_attempt_at, last_error_code,
                    telegram_message_id, sent_at, duplicate_risk, created_at, updated_at
                FROM telegram_deliveries_legacy
                """
            )
            after = int(connection.execute("SELECT COUNT(*) FROM telegram_deliveries").fetchone()[0])
            if before != after:
                raise DeliveryOutboxError("legacy delivery outbox migration row count mismatch")
            connection.execute("DROP TABLE telegram_deliveries_legacy")
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    @classmethod
    def inspect_existing(
        cls,
        path: str,
        snapshot_id: str,
        destination_chat_id: str,
        destination_message_thread_id: int | None = None,
    ) -> DeliveryRecord | None:
        db_path = Path(path)
        if not db_path.is_file():
            return None
        snapshot = _required(snapshot_id, "snapshot_id", 128)
        destination = _required(destination_chat_id, "destination_chat_id", 64)
        try:
            connection = sqlite3.connect(
                f"file:{db_path.resolve()}?mode=ro",
                timeout=5.0,
                uri=True,
            )
            connection.row_factory = sqlite3.Row
            try:
                columns = {
                    str(item[1]) for item in connection.execute("PRAGMA table_info(telegram_deliveries)")
                }
                if "destination_message_thread_id" not in columns:
                    if destination_message_thread_id is not None:
                        return None
                    row = connection.execute(
                        "SELECT * FROM telegram_deliveries "
                        "WHERE snapshot_id = ? AND destination_chat_id = ?",
                        (snapshot, destination),
                    ).fetchone()
                else:
                    row = connection.execute(
                        "SELECT * FROM telegram_deliveries "
                        "WHERE snapshot_id = ? AND destination_chat_id = ? "
                        "AND destination_message_thread_id = ?",
                        (snapshot, destination, _thread_db_value(destination_message_thread_id)),
                    ).fetchone()
            except sqlite3.OperationalError as error:
                if "no such table: telegram_deliveries" in str(error):
                    return None
                raise DeliveryOutboxError("delivery outbox inspection failed") from error
            finally:
                connection.close()
        except sqlite3.Error as error:
            raise DeliveryOutboxError("delivery outbox inspection failed") from error
        return None if row is None else _record(row)

    def enqueue(
        self,
        snapshot: ReportSnapshot,
        destination_chat_id: str,
        rendered: RenderedMessage,
        *,
        destination_message_thread_id: int | None = None,
        now: datetime | None = None,
    ) -> tuple[DeliveryRecord, bool]:
        created_at = _utc(now)
        destination = _required(destination_chat_id, "destination_chat_id", 64)
        thread_id = _thread_db_value(destination_message_thread_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE snapshot_id = ? AND destination_chat_id = ? "
                "AND destination_message_thread_id = ?",
                (snapshot.id, destination, thread_id),
            ).fetchone()
            if existing is not None:
                if existing["snapshot_sha256"] != snapshot.payload_sha256:
                    connection.rollback()
                    raise DeliveryOutboxError(
                        "snapshot identity is already bound to different immutable content"
                    )
                connection.commit()
                return _record(existing), True
            cursor = connection.execute(
                """
                INSERT INTO telegram_deliveries (
                    snapshot_id, snapshot_sha256, destination_chat_id, destination_message_thread_id,
                    rendered_text, button_url, state, attempts,
                    available_at, duplicate_risk, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, 0, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.payload_sha256,
                    destination,
                    thread_id,
                    rendered.text,
                    rendered.button_url,
                    _stamp(created_at),
                    _stamp(created_at),
                    _stamp(created_at),
                ),
            )
            row = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.commit()
            assert row is not None
            return _record(row), False

    def recover_stale_sending(
        self,
        *,
        stale_after: timedelta,
        now: datetime | None = None,
    ) -> int:
        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        recovered_at = _utc(now)
        stale_before = recovered_at - stale_after
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE telegram_deliveries
                SET state = 'retry_wait',
                    available_at = ?,
                    locked_at = NULL,
                    last_error_code = 'delivery_outcome_unknown_after_restart',
                    duplicate_risk = 1,
                    updated_at = ?
                WHERE state = 'sending' AND locked_at IS NOT NULL AND locked_at <= ?
                """,
                (_stamp(recovered_at), _stamp(recovered_at), _stamp(stale_before)),
            )
            return int(cursor.rowcount)

    def claim_next(self, *, now: datetime | None = None) -> DeliveryRecord | None:
        claimed_at = _utc(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM telegram_deliveries
                WHERE state IN ('pending', 'retry_wait') AND available_at <= ?
                ORDER BY available_at, id
                LIMIT 1
                """,
                (_stamp(claimed_at),),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE telegram_deliveries
                SET state = 'sending', attempts = attempts + 1,
                    locked_at = ?, last_attempt_at = ?, last_error_code = NULL, updated_at = ?
                WHERE id = ?
                """,
                (_stamp(claimed_at), _stamp(claimed_at), _stamp(claimed_at), row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.commit()
            assert claimed is not None
            return _record(claimed)

    def claim_next_for_destination(
        self,
        destination_chat_id: str,
        *,
        destination_message_thread_id: int | None = None,
        now: datetime | None = None,
    ) -> DeliveryRecord | None:
        claimed_at = _utc(now)
        destination = _required(destination_chat_id, "destination_chat_id", 64)
        thread_id = _thread_db_value(destination_message_thread_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM telegram_deliveries
                WHERE state IN ('pending', 'retry_wait') AND available_at <= ?
                  AND destination_chat_id = ? AND destination_message_thread_id = ?
                ORDER BY available_at, id
                LIMIT 1
                """,
                (_stamp(claimed_at), destination, thread_id),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE telegram_deliveries
                SET state = 'sending', attempts = attempts + 1,
                    locked_at = ?, last_attempt_at = ?, last_error_code = NULL, updated_at = ?
                WHERE id = ?
                """,
                (_stamp(claimed_at), _stamp(claimed_at), _stamp(claimed_at), row["id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?", (row["id"],)
            ).fetchone()
            connection.commit()
            assert claimed is not None
            return _record(claimed)

    def claim_exact(
        self,
        snapshot_id: str,
        destination_chat_id: str,
        *,
        destination_message_thread_id: int | None = None,
        now: datetime | None = None,
    ) -> DeliveryRecord:
        claimed_at = _utc(now)
        snapshot = _required(snapshot_id, "snapshot_id", 128)
        destination = _required(destination_chat_id, "destination_chat_id", 64)
        thread_id = _thread_db_value(destination_message_thread_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM telegram_deliveries "
                "WHERE snapshot_id = ? AND destination_chat_id = ? "
                "AND destination_message_thread_id = ?",
                (snapshot, destination, thread_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DeliveryOutboxError("exact delivery was not found")
            if row["state"] != DeliveryState.PENDING.value:
                connection.rollback()
                raise DeliveryOutboxError("exact delivery is not pending")
            if _parse_stamp(str(row["available_at"])) > claimed_at:
                connection.rollback()
                raise DeliveryOutboxError("exact delivery is not available")
            cursor = connection.execute(
                """
                UPDATE telegram_deliveries
                SET state = 'sending', attempts = attempts + 1,
                    locked_at = ?, last_attempt_at = ?, last_error_code = NULL, updated_at = ?
                WHERE id = ? AND state = 'pending'
                """,
                (
                    _stamp(claimed_at),
                    _stamp(claimed_at),
                    _stamp(claimed_at),
                    row["id"],
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise DeliveryOutboxError("exact delivery state changed before claim")
            claimed = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?",
                (row["id"],),
            ).fetchone()
            connection.commit()
            assert claimed is not None
            return _record(claimed)

    def mark_sent(
        self,
        delivery_id: int,
        *,
        telegram_message_id: int,
        now: datetime | None = None,
    ) -> DeliveryRecord:
        sent_at = _utc(now)
        return self._transition_from_sending(
            delivery_id,
            state=DeliveryState.SENT,
            available_at=sent_at,
            error_code=None,
            telegram_message_id=telegram_message_id,
            sent_at=sent_at,
            now=sent_at,
        )

    def mark_retry(
        self,
        delivery_id: int,
        *,
        delay: timedelta,
        error_code: str,
        now: datetime | None = None,
    ) -> DeliveryRecord:
        if delay.total_seconds() < 0:
            raise ValueError("retry delay cannot be negative")
        attempted_at = _utc(now)
        return self._transition_from_sending(
            delivery_id,
            state=DeliveryState.RETRY_WAIT,
            available_at=attempted_at + delay,
            error_code=error_code,
            telegram_message_id=None,
            sent_at=None,
            now=attempted_at,
        )
    def mark_failed(
        self,
        delivery_id: int,
        *,
        error_code: str,
        duplicate_risk: bool = False,
        now: datetime | None = None,
    ) -> DeliveryRecord:
        failed_at = _utc(now)
        return self._transition_from_sending(
            delivery_id,
            state=DeliveryState.FAILED,
            available_at=failed_at,
            error_code=error_code,
            telegram_message_id=None,
            sent_at=None,
            now=failed_at,
            duplicate_risk=duplicate_risk,
        )

    def _transition_from_sending(
        self,
        delivery_id: int,
        *,
        state: DeliveryState,
        available_at: datetime,
        error_code: str | None,
        telegram_message_id: int | None,
        sent_at: datetime | None,
        now: datetime,
        duplicate_risk: bool = False,
    ) -> DeliveryRecord:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?", (delivery_id,)
            ).fetchone()
            if row is None:
                connection.rollback()
                raise DeliveryOutboxError("delivery was not found")
            if row["state"] != DeliveryState.SENDING.value:
                connection.rollback()
                raise DeliveryOutboxError("delivery is not in sending state")
            connection.execute(
                """
                UPDATE telegram_deliveries
                SET state = ?, available_at = ?, locked_at = NULL,
                    last_error_code = ?, telegram_message_id = ?, sent_at = ?, updated_at = ?,
                    duplicate_risk = MAX(duplicate_risk, ?)
                WHERE id = ?
                """,
                (
                    state.value,
                    _stamp(available_at),
                    _optional_error(error_code),
                    telegram_message_id,
                    None if sent_at is None else _stamp(sent_at),
                    _stamp(now),
                    int(duplicate_risk),
                    delivery_id,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE id = ?", (delivery_id,)
            ).fetchone()
            connection.commit()
            assert updated is not None
            return _record(updated)

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state, COUNT(*) AS count FROM telegram_deliveries GROUP BY state"
            ).fetchall()
            duplicate_risk = connection.execute(
                "SELECT COUNT(*) FROM telegram_deliveries WHERE duplicate_risk = 1"
            ).fetchone()[0]
        counts = {state.value: 0 for state in DeliveryState}
        counts.update({str(row["state"]): int(row["count"]) for row in rows})
        counts["duplicate_risk"] = int(duplicate_risk)
        return counts

    def get_by_snapshot(
        self,
        snapshot_id: str,
        destination_chat_id: str,
        destination_message_thread_id: int | None = None,
    ) -> DeliveryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM telegram_deliveries WHERE snapshot_id = ? AND destination_chat_id = ? "
                "AND destination_message_thread_id = ?",
                (snapshot_id, destination_chat_id, _thread_db_value(destination_message_thread_id)),
            ).fetchone()
        return None if row is None else _record(row)


def _record(row: sqlite3.Row) -> DeliveryRecord:
    return DeliveryRecord(
        id=int(row["id"]),
        snapshot_id=str(row["snapshot_id"]),
        snapshot_sha256=str(row["snapshot_sha256"]),
        destination_chat_id=str(row["destination_chat_id"]),
        destination_message_thread_id=_thread_record_value(row),
        text=str(row["rendered_text"]),
        button_url=str(row["button_url"]),
        state=DeliveryState(str(row["state"])),
        attempts=int(row["attempts"]),
        available_at=_parse_stamp(row["available_at"]),
        locked_at=_parse_optional_stamp(row["locked_at"]),
        last_attempt_at=_parse_optional_stamp(row["last_attempt_at"]),
        last_error_code=(None if row["last_error_code"] is None else str(row["last_error_code"])),
        telegram_message_id=(
            None if row["telegram_message_id"] is None else int(row["telegram_message_id"])
        ),
        sent_at=_parse_optional_stamp(row["sent_at"]),
        duplicate_risk=bool(row["duplicate_risk"]),
    )


def _thread_db_value(value: int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("destination_message_thread_id must be a positive integer when set")
    return value


def _thread_record_value(row: sqlite3.Row) -> int | None:
    try:
        value = int(row["destination_message_thread_id"])
    except (IndexError, KeyError):
        return None
    return None if value == 0 else value


def _utc(value: datetime | None) -> datetime:
    resolved = value or datetime.now(UTC)
    if resolved.tzinfo is None or resolved.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return resolved.astimezone(UTC)


def _stamp(value: datetime) -> str:
    return _utc(value).isoformat(timespec="microseconds")


def _parse_stamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DeliveryOutboxError("stored delivery timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def _parse_optional_stamp(value: object) -> datetime | None:
    return None if value is None else _parse_stamp(str(value))


def _required(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must contain 1..{maximum} characters")
    return normalized


def _optional_error(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:96]
