from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    create_engine,
    delete,
    func,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.contracts import TelemetryEvent
from app.committed_receipts import CommittedReceiptIdentity, prepare_committed_receipt


TELEMETRY_HISTORY_ADVISORY_LOCK_ID = 263_000_001


class Base(DeclarativeBase):
    pass


class TelemetrySample(Base):
    __tablename__ = "telemetry_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    alarm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_status: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_payload_retained: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TelemetryCommittedReceipt(Base):
    """Transactional intent only; a separate authenticated publisher owns delivery."""

    __tablename__ = "telemetry_committed_receipts"

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    node_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "ix_telemetry_committed_receipts_pending",
    TelemetryCommittedReceipt.published_at,
    TelemetryCommittedReceipt.committed_at,
)


class TelemetryLatest(Base):
    """Bounded durable projection containing one row per canonical telemetry series."""

    __tablename__ = "telemetry_latest"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    quality: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    equipment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    alarm: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    raw_status: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    stale_after_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def raw_payload(self) -> dict[str, Any]:
        """Expose only delivery metadata needed by the existing projection contract."""
        if self.stale_after_seconds is None:
            return {}
        return {"stale_after_seconds": self.stale_after_seconds}


class DeadLetterEvent(Base):
    __tablename__ = "telemetry_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    topic: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_detail: Mapped[str] = mapped_column(String(2048), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_size: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


Index(
    "ix_telemetry_channel_captured",
    TelemetrySample.node_id,
    TelemetrySample.equipment_id,
    TelemetrySample.channel_id,
    TelemetrySample.captured_at,
)
Index(
    "ix_telemetry_metric_captured",
    TelemetrySample.metric,
    TelemetrySample.captured_at,
)
Index(
    "ix_telemetry_latest_lookup",
    TelemetrySample.node_id,
    TelemetrySample.equipment_id,
    TelemetrySample.channel_id,
    TelemetrySample.metric,
    TelemetrySample.captured_at,
    TelemetrySample.event_id,
)
Index(
    "ix_telemetry_history_lookup",
    TelemetrySample.node_id,
    TelemetrySample.channel_id,
    TelemetrySample.captured_at,
    TelemetrySample.event_id,
)
Index(
    "uq_telemetry_latest_series",
    TelemetryLatest.node_id,
    TelemetryLatest.equipment_id,
    TelemetryLatest.channel_id,
    TelemetryLatest.metric,
    unique=True,
)
Index(
    "ix_telemetry_latest_order",
    TelemetryLatest.captured_at,
    TelemetryLatest.event_id,
)
Index(
    "ix_telemetry_latest_filters",
    TelemetryLatest.quality,
    TelemetryLatest.alarm,
    TelemetryLatest.captured_at,
    TelemetryLatest.event_id,
)
Index(
    "ix_dead_letter_reason_received",
    DeadLetterEvent.reason_code,
    DeadLetterEvent.received_at,
)
Index(
    "ix_dead_letter_received",
    DeadLetterEvent.received_at,
)


@dataclass(frozen=True)
class TelemetryQuery:
    node_id: str | None = None
    equipment_id: str | None = None
    channel_id: str | None = None
    metric: str | None = None
    quality: str | None = None
    alarm: str | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None
    received_before: datetime | None = None


@dataclass(frozen=True)
class RetentionResult:
    telemetry_deleted: int = 0
    raw_payloads_redacted: int = 0
    dead_letters_deleted: int = 0


def _stale_after_seconds(raw_payload: dict[str, Any]) -> float | None:
    value = raw_payload.get("stale_after_seconds")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if resolved > 0 else None


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        connect_timeout_seconds: int = 3,
    ) -> None:
        connect_args: dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        elif database_url.startswith("postgresql"):
            connect_args["connect_timeout"] = connect_timeout_seconds

        self.engine = create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._sessions = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    @staticmethod
    def _latest_values(
        *,
        values: dict[str, Any],
        sample_id: int,
        received_at: datetime,
        raw_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "sample_id": sample_id,
            "event_id": values["event_id"],
            "node_id": values["node_id"],
            "captured_at": values["captured_at"],
            "metric": values["metric"],
            "value": values["value"],
            "unit": values["unit"],
            "quality": values["quality"],
            "source": values["source"],
            "equipment_id": values["equipment_id"],
            "channel_id": values["channel_id"],
            "alarm": values["alarm"],
            "raw_value": values["raw_value"],
            "raw_status": values["raw_status"],
            "stale_after_seconds": _stale_after_seconds(raw_payload),
            "received_at": received_at,
        }

    @staticmethod
    def _upsert_latest(
        connection: Any,
        *,
        dialect: str,
        values: dict[str, Any],
    ) -> None:
        table = TelemetryLatest.__table__
        series_columns = ["node_id", "equipment_id", "channel_id", "metric"]
        update_columns = {
            key: value
            for key, value in values.items()
            if key not in {"node_id", "equipment_id", "channel_id", "metric"}
        }

        if dialect in {"postgresql", "sqlite"}:
            insert_fn = postgresql_insert if dialect == "postgresql" else sqlite_insert
            statement = insert_fn(table).values(**values)
            excluded = statement.excluded
            newer = or_(
                excluded.captured_at > table.c.captured_at,
                (
                    (excluded.captured_at == table.c.captured_at)
                    & (excluded.sample_id > table.c.sample_id)
                ),
            )
            statement = statement.on_conflict_do_update(
                index_elements=series_columns,
                set_=update_columns,
                where=newer,
            )
            connection.execute(statement)
            return

        key_filter = (
            (table.c.node_id == values["node_id"])
            & (table.c.equipment_id == values["equipment_id"])
            & (table.c.channel_id == values["channel_id"])
            & (table.c.metric == values["metric"])
        )
        existing = connection.execute(
            select(table.c.id, table.c.captured_at, table.c.sample_id).where(key_filter)
        ).first()
        if existing is None:
            connection.execute(table.insert().values(**values))
            return

        existing_captured_at = existing.captured_at
        incoming_captured_at = values["captured_at"]
        if existing_captured_at.tzinfo is None and incoming_captured_at.tzinfo is not None:
            existing_captured_at = existing_captured_at.replace(tzinfo=UTC)
        if incoming_captured_at.tzinfo is None and existing_captured_at.tzinfo is not None:
            incoming_captured_at = incoming_captured_at.replace(tzinfo=UTC)

        if (
            incoming_captured_at > existing_captured_at
            or (
                incoming_captured_at == existing_captured_at
                and values["sample_id"] > existing.sample_id
            )
        ):
            connection.execute(
                update(table).where(table.c.id == existing.id).values(**update_columns)
            )

    def persist(
        self,
        event: TelemetryEvent,
        raw_payload: dict[str, Any],
        *,
        receipt_identity: CommittedReceiptIdentity | None = None,
        receipt_outbox_max_pending: int = 10_000,
        connection: Any | None = None,
    ) -> bool:
        """Persist telemetry and optional central-receipt intent atomically.

        receipt_identity MUST come from a successful node-registry ingress
        authorization and a separately verified authenticated MQTT boundary.
        This parameter is opt-in; no runtime call path currently supplies it.
        """
        if receipt_identity is not None:
            if receipt_outbox_max_pending < 1:
                raise ValueError("invalid_receipt_outbox_capacity")
            receipt_identity.validate_raw(event, raw_payload)

        values = {
            "event_id": str(event.event_id),
            "node_id": event.node_id,
            "captured_at": event.captured_at,
            "metric": event.metric,
            "value": event.value,
            "unit": event.unit,
            "quality": event.quality,
            "source": event.source,
            "equipment_id": event.equipment_id,
            "channel_id": event.channel_id,
            "alarm": event.alarm,
            "raw_value": event.raw_value,
            "raw_status": event.raw_status,
            "raw_payload": raw_payload,
            "raw_payload_retained": True,
        }

        table = TelemetrySample.__table__
        dialect = self.engine.dialect.name
        if receipt_identity is not None and dialect != "postgresql":
            raise RuntimeError("postgresql_required_for_committed_receipt")

        if connection is not None and not connection.in_transaction():
            raise RuntimeError("receipt_persist_requires_active_transaction")

        with (self.engine.begin() if connection is None else nullcontext(connection)) as connection:
            if receipt_identity is not None and dialect == "postgresql":
                # Serialize capacity checks across concurrent central workers.
                connection.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_id)"),
                    {"lock_id": 263_000_002},
                )
            if dialect == "postgresql":
                connection.execute(
                    text("SELECT pg_advisory_xact_lock_shared(:lock_id)"),
                    {"lock_id": TELEMETRY_HISTORY_ADVISORY_LOCK_ID},
                )
                statement = (
                    postgresql_insert(table)
                    .values(**values, received_at=func.clock_timestamp())
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(table.c.id, table.c.received_at)
                )
                inserted = connection.execute(statement).first()
            elif dialect == "sqlite":
                statement = (
                    sqlite_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(table.c.id, table.c.received_at)
                )
                inserted = connection.execute(statement).first()
            else:
                existing = connection.execute(
                    select(TelemetrySample.id).where(
                        TelemetrySample.event_id == str(event.event_id)
                    )
                ).first()
                if existing is not None:
                    return False
                result = connection.execute(table.insert().values(**values))
                sample_id = int(result.inserted_primary_key[0])
                inserted = connection.execute(
                    select(table.c.id, table.c.received_at).where(table.c.id == sample_id)
                ).first()

            if inserted is None:
                if receipt_identity is not None:
                    existing = connection.execute(
                        select(TelemetrySample.raw_payload, TelemetrySample.node_id)
                        .where(TelemetrySample.event_id == str(event.event_id))
                    ).first()
                    if (
                        existing is None
                        or existing.node_id != receipt_identity.node_id
                        or existing.raw_payload != raw_payload
                    ):
                        raise ValueError("receipt_duplicate_event_identity_conflict")
                    self._queue_committed_receipt(
                        connection,
                        event_id=str(event.event_id),
                        identity=receipt_identity,
                        max_pending=receipt_outbox_max_pending,
                    )
                return False

            latest_values = self._latest_values(
                values=values,
                sample_id=int(inserted.id),
                received_at=inserted.received_at,
                raw_payload=raw_payload,
            )
            self._upsert_latest(
                connection,
                dialect=dialect,
                values=latest_values,
            )
            if receipt_identity is not None:
                self._queue_committed_receipt(
                    connection,
                    event_id=str(event.event_id),
                    identity=receipt_identity,
                    max_pending=receipt_outbox_max_pending,
                )
            return True

    @staticmethod
    def _queue_committed_receipt(
        connection: Any,
        *,
        event_id: str,
        identity: CommittedReceiptIdentity,
        max_pending: int,
    ) -> None:
        """Enqueue only under the caller's open telemetry transaction."""
        table = TelemetryCommittedReceipt.__table__
        existing = connection.execute(
            select(table).where(table.c.event_id == event_id)
        ).mappings().first()
        if existing is not None:
            if (
                existing["organization_id"] != identity.organization_id
                or existing["node_id"] != identity.node_id
                or existing["node_sequence"] != identity.node_sequence
                or existing["topic"] != identity.receipt_topic
            ):
                raise ValueError("receipt_outbox_identity_conflict")
            if existing["published_at"] is not None:
                pending = connection.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.published_at.is_(None))
                )
                if pending is None or pending >= max_pending:
                    raise RuntimeError("receipt_outbox_capacity_reached")
                # A valid replay may request a fresh receipt if an old MQTT
                # reply was dropped or exceeded the seven-day freshness budget.
                # The original immutable PostgreSQL sample is first verified
                # by persist() before this reissue is permitted.
                payload, observed = prepare_committed_receipt(
                    event_id=event_id,
                    identity=identity,
                    receipt_id=str(uuid4()),
                )
                connection.execute(
                    table.update()
                    .where(table.c.event_id == event_id)
                    .values(
                        receipt_id=payload["receipt_id"],
                        payload=payload,
                        committed_at=observed,
                        published_at=None,
                        attempts=0,
                        next_attempt_at=None,
                    )
                )
            return
        pending = connection.scalar(
            select(func.count())
            .select_from(table)
            .where(table.c.published_at.is_(None))
        )
        if pending is None or pending >= max_pending:
            raise RuntimeError("receipt_outbox_capacity_reached")
        receipt_id = str(uuid4())
        payload, committed_at = prepare_committed_receipt(
            event_id=event_id, identity=identity, receipt_id=receipt_id
        )
        connection.execute(
            table.insert().values(
                event_id=event_id,
                receipt_id=receipt_id,
                organization_id=identity.organization_id,
                node_id=identity.node_id,
                node_sequence=identity.node_sequence,
                topic=identity.receipt_topic,
                payload=payload,
                committed_at=committed_at,
                published_at=None,
                attempts=0,
                next_attempt_at=None,
            )
        )

    def persist_dead_letter(
        self,
        *,
        payload: bytes,
        payload_size: int,
        payload_truncated: bool,
        reason_code: str,
        reason_detail: str,
        topic: str | None,
    ) -> int:
        statement = DeadLetterEvent.__table__.insert().values(
            topic=topic,
            reason_code=reason_code,
            reason_detail=reason_detail[:2048],
            payload=payload,
            payload_size=payload_size,
            payload_truncated=payload_truncated,
        )
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            return int(result.inserted_primary_key[0])

    @staticmethod
    def _apply_filters(statement: Any, query: TelemetryQuery) -> Any:
        filters = []
        if query.node_id is not None:
            filters.append(TelemetrySample.node_id == query.node_id)
        if query.equipment_id is not None:
            filters.append(TelemetrySample.equipment_id == query.equipment_id)
        if query.channel_id is not None:
            filters.append(TelemetrySample.channel_id == query.channel_id)
        if query.metric is not None:
            filters.append(TelemetrySample.metric == query.metric)
        if query.quality is not None:
            filters.append(TelemetrySample.quality == query.quality)
        if query.alarm is not None:
            filters.append(TelemetrySample.alarm == query.alarm)
        if query.from_at is not None:
            filters.append(TelemetrySample.captured_at >= query.from_at)
        if query.to_at is not None:
            filters.append(TelemetrySample.captured_at < query.to_at)
        if query.received_before is not None:
            filters.append(TelemetrySample.received_at <= query.received_before)
        if filters:
            statement = statement.where(*filters)
        return statement

    @staticmethod
    def _apply_latest_filters(statement: Any, query: TelemetryQuery) -> Any:
        filters = []
        if query.node_id is not None:
            filters.append(TelemetryLatest.node_id == query.node_id)
        if query.equipment_id is not None:
            filters.append(TelemetryLatest.equipment_id == query.equipment_id)
        if query.channel_id is not None:
            filters.append(TelemetryLatest.channel_id == query.channel_id)
        if query.metric is not None:
            filters.append(TelemetryLatest.metric == query.metric)
        if query.quality is not None:
            filters.append(TelemetryLatest.quality == query.quality)
        if query.alarm is not None:
            filters.append(TelemetryLatest.alarm == query.alarm)
        if query.from_at is not None:
            filters.append(TelemetryLatest.captured_at >= query.from_at)
        if query.to_at is not None:
            filters.append(TelemetryLatest.captured_at < query.to_at)
        if query.received_before is not None:
            filters.append(TelemetryLatest.received_at <= query.received_before)
        if filters:
            statement = statement.where(*filters)
        return statement

    def latest_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetryLatest]:
        statement = select(TelemetryLatest)
        statement = self._apply_latest_filters(statement, query)
        statement = (
            statement.order_by(
                TelemetryLatest.captured_at.desc(),
                TelemetryLatest.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._sessions() as session:
            return list(session.scalars(statement))

    def _history_statement(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> Any:
        statement = select(TelemetrySample)
        statement = self._apply_filters(statement, query)
        return (
            statement.order_by(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

    def history_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetrySample]:
        statement = self._history_statement(
            query=query,
            limit=limit,
            offset=offset,
        )
        with self._sessions() as session:
            return list(session.scalars(statement))

    def history_snapshot_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
        snapshot_at: datetime | None = None,
    ) -> tuple[list[TelemetrySample], datetime]:
        with self._sessions() as session:
            with session.begin():
                resolved_snapshot_at = snapshot_at
                if resolved_snapshot_at is None:
                    if self.engine.dialect.name == "postgresql":
                        session.execute(
                            text("SELECT pg_advisory_xact_lock(:lock_id)"),
                            {"lock_id": TELEMETRY_HISTORY_ADVISORY_LOCK_ID},
                        )
                        resolved_snapshot_at = session.scalar(
                            select(func.clock_timestamp())
                        )
                    else:
                        resolved_snapshot_at = datetime.now(UTC)

                if not isinstance(resolved_snapshot_at, datetime):
                    raise RuntimeError("Unable to establish telemetry history snapshot")

                snapshot_query = replace(
                    query,
                    received_before=resolved_snapshot_at,
                )
                statement = self._history_statement(
                    query=snapshot_query,
                    limit=limit,
                    offset=offset,
                )
                rows = list(session.scalars(statement))

        return rows, resolved_snapshot_at

    def cleanup_retention(
        self,
        *,
        now: datetime,
        telemetry_retention_days: int,
        raw_payload_retention_days: int,
        dead_letter_retention_days: int,
        batch_size: int,
    ) -> RetentionResult:
        telemetry_cutoff = now - timedelta(days=telemetry_retention_days)
        raw_payload_cutoff = now - timedelta(days=raw_payload_retention_days)
        dead_letter_cutoff = now - timedelta(days=dead_letter_retention_days)

        with self.engine.begin() as connection:
            telemetry_ids = list(
                connection.scalars(
                    select(TelemetrySample.id)
                    .where(TelemetrySample.captured_at < telemetry_cutoff)
                    .order_by(TelemetrySample.id)
                    .limit(batch_size)
                )
            )
            if telemetry_ids:
                connection.execute(
                    delete(TelemetrySample).where(
                        TelemetrySample.id.in_(telemetry_ids)
                    )
                )

            raw_payload_ids = list(
                connection.scalars(
                    select(TelemetrySample.id)
                    .where(
                        TelemetrySample.received_at < raw_payload_cutoff,
                        TelemetrySample.raw_payload_retained.is_(True),
                    )
                    .order_by(TelemetrySample.id)
                    .limit(batch_size)
                )
            )
            if raw_payload_ids:
                connection.execute(
                    update(TelemetrySample)
                    .where(TelemetrySample.id.in_(raw_payload_ids))
                    .values(raw_payload={}, raw_payload_retained=False)
                )

            dead_letter_ids = list(
                connection.scalars(
                    select(DeadLetterEvent.id)
                    .where(DeadLetterEvent.received_at < dead_letter_cutoff)
                    .order_by(DeadLetterEvent.id)
                    .limit(batch_size)
                )
            )
            if dead_letter_ids:
                connection.execute(
                    delete(DeadLetterEvent).where(
                        DeadLetterEvent.id.in_(dead_letter_ids)
                    )
                )

        return RetentionResult(
            telemetry_deleted=len(telemetry_ids),
            raw_payloads_redacted=len(raw_payload_ids),
            dead_letters_deleted=len(dead_letter_ids),
        )

    def count_samples(self) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(select(func.count()).select_from(TelemetrySample))
                or 0
            )

    def count_latest_samples(self) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(select(func.count()).select_from(TelemetryLatest))
                or 0
            )

    def count_dead_letters(self) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(select(func.count()).select_from(DeadLetterEvent))
                or 0
            )

    def count_retained_raw_payloads(self) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(TelemetrySample)
                    .where(TelemetrySample.raw_payload_retained.is_(True))
                )
                or 0
            )

    def list_dead_letters(self, limit: int = 100) -> list[DeadLetterEvent]:
        statement = (
            select(DeadLetterEvent)
            .order_by(DeadLetterEvent.received_at.desc(), DeadLetterEvent.id.desc())
            .limit(limit)
        )
        with self._sessions() as session:
            return list(session.scalars(statement))