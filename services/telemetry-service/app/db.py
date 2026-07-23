from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    create_engine,
    func,
    select,
    text,
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


class Database:
    def __init__(self, database_url: str) -> None:
        connect_args: dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

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
        }

        table = TelemetrySample.__table__
        dialect = self.engine.dialect.name

        with self.engine.begin() as connection:
            if dialect == "postgresql":
                statement = (
                    postgresql_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
            elif dialect == "sqlite":
                statement = (
                    sqlite_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
            else:
                existing = connection.execute(
                    select(TelemetrySample.id).where(
                        TelemetrySample.event_id == str(event.event_id)
                    )
                ).first()
                if existing is not None:
                    return False
                statement = table.insert().values(**values)

            result = connection.execute(statement)
            return result.rowcount == 1

    def count_samples(self) -> int:
        with self._sessions() as session:
            return int(
                session.scalar(select(func.count()).select_from(TelemetrySample))
                or 0
            )
