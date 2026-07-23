from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

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
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.contracts import TelemetryEvent


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


@dataclass(frozen=True)
class RetentionResult:
    telemetry_deleted: int = 0
    raw_payloads_redacted: int = 0
    dead_letters_deleted: int = 0


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

    def persist(self, event: TelemetryEvent, raw_payload: dict[str, Any]) -> bool:
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

        with self.engine.begin() as connection:
            if dialect == "postgresql":
                statement = (
                    postgresql_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                    .returning(table.c.event_id)
                )
                inserted_event_id = connection.execute(statement).scalar_one_or_none()
                return inserted_event_id is not None

            if dialect == "sqlite":
                statement = (
                    sqlite_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
                result = connection.execute(statement)
                return result.rowcount == 1

            existing = connection.execute(
                select(TelemetrySample.id).where(
                    TelemetrySample.event_id == str(event.event_id)
                )
            ).first()
            if existing is not None:
                return False
            connection.execute(table.insert().values(**values))
            return True

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
        if filters:
            statement = statement.where(*filters)
        return statement

    def latest_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetrySample]:
        rank = func.row_number().over(
            partition_by=(
                TelemetrySample.node_id,
                TelemetrySample.equipment_id,
                TelemetrySample.channel_id,
                TelemetrySample.metric,
            ),
            order_by=(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.id.desc(),
            ),
        ).label("sample_rank")
        ranked_statement = select(
            TelemetrySample.id.label("sample_id"),
            rank,
        )
        ranked_statement = self._apply_filters(ranked_statement, query)
        ranked = ranked_statement.subquery()

        statement = (
            select(TelemetrySample)
            .join(ranked, TelemetrySample.id == ranked.c.sample_id)
            .where(ranked.c.sample_rank == 1)
            .order_by(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._sessions() as session:
            return list(session.scalars(statement))

    def history_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetrySample]:
        statement = select(TelemetrySample)
        statement = self._apply_filters(statement, query)
        statement = (
            statement.order_by(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._sessions() as session:
            return list(session.scalars(statement))

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
