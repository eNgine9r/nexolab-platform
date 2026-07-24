from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import TelemetryEvent
from app.db import Base, Database, TelemetryQuery, TelemetrySample
from app.sessions.models import (
    SessionChannelBinding,
    SessionConfigSnapshot,
    SessionStage,
    TestSession,
)


ATTRIBUTION_RESOLVER_VERSION = "captured-at-interval-v1"


class TelemetryAttributionError(RuntimeError):
    pass


class TelemetrySessionContext(Base):
    __tablename__ = "telemetry_session_contexts"
    __table_args__ = (
        Index(
            "ix_telemetry_context_session_captured",
            "session_id",
            "captured_at",
            "telemetry_event_id",
        ),
        Index(
            "ix_telemetry_context_session_stage_captured",
            "session_id",
            "stage_id",
            "captured_at",
            "telemetry_event_id",
        ),
        Index("ix_telemetry_context_binding", "binding_id"),
        Index("ix_telemetry_context_snapshot", "config_snapshot_id"),
    )

    telemetry_event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "telemetry_samples.event_id",
            name="fk_telemetry_context_event_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "test_sessions.id",
            name="fk_telemetry_context_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    stage_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(
            "session_stages.id",
            name="fk_telemetry_context_stage_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    binding_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_channel_bindings.id",
            name="fk_telemetry_context_binding_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    config_snapshot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_config_snapshots.id",
            name="fk_telemetry_context_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attributed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)


@dataclass(frozen=True, slots=True)
class ResolvedTelemetryContext:
    session_id: str
    stage_id: str | None
    binding_id: str
    config_snapshot_id: str


@dataclass(frozen=True)
class SessionTelemetryQuery:
    stage_id: str | None = None
    node_id: str | None = None
    equipment_id: str | None = None
    channel_id: str | None = None
    metric: str | None = None
    quality: str | None = None
    alarm: str | None = None
    from_at: datetime | None = None
    to_at: datetime | None = None


class SessionAwareDatabase(Database):
    """Telemetry persistence with immutable laboratory-session attribution."""

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

        with self.engine.begin() as connection:
            if not self._insert_telemetry_sample(connection, values):
                return False

            context = resolve_telemetry_context(connection, event)
            if context is not None:
                connection.execute(
                    TelemetrySessionContext.__table__.insert().values(
                        telemetry_event_id=str(event.event_id),
                        session_id=context.session_id,
                        stage_id=context.stage_id,
                        binding_id=context.binding_id,
                        config_snapshot_id=context.config_snapshot_id,
                        captured_at=event.captured_at,
                        resolver_version=ATTRIBUTION_RESOLVER_VERSION,
                    )
                )
        return True

    def session_exists(self, session_id: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(TestSession.id).where(TestSession.id == session_id)
                ).scalar_one_or_none()
                is not None
            )

    def session_latest_samples(
        self,
        *,
        session_id: str,
        query: SessionTelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sample = TelemetrySample.__table__
        context = TelemetrySessionContext.__table__
        rank = func.row_number().over(
            partition_by=(
                sample.c.node_id,
                sample.c.equipment_id,
                sample.c.channel_id,
                sample.c.metric,
            ),
            order_by=(sample.c.captured_at.desc(), sample.c.id.desc()),
        ).label("sample_rank")
        ranked = (
            select(sample.c.id.label("sample_id"), rank)
            .select_from(sample.join(context, sample.c.event_id == context.c.telemetry_event_id))
        )
        ranked = _apply_session_filters(
            ranked,
            session_id=session_id,
            query=query,
        ).subquery()
        statement = (
            _attributed_sample_select()
            .join(ranked, sample.c.id == ranked.c.sample_id)
            .where(ranked.c.sample_rank == 1)
            .order_by(sample.c.captured_at.desc(), sample.c.event_id.desc())
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def session_history_samples(
        self,
        *,
        session_id: str,
        query: SessionTelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        sample = TelemetrySample.__table__
        statement = _apply_session_filters(
            _attributed_sample_select(),
            session_id=session_id,
            query=query,
        )
        statement = (
            statement.order_by(sample.c.captured_at.desc(), sample.c.event_id.desc())
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(statement).mappings()]

    def context_for_event(self, event_id: str) -> TelemetrySessionContext | None:
        with self._sessions() as session:
            return session.get(TelemetrySessionContext, event_id)

    def _insert_telemetry_sample(
        self,
        connection: Connection,
        values: dict[str, Any],
    ) -> bool:
        table = TelemetrySample.__table__
        dialect = self.engine.dialect.name
        if dialect == "postgresql":
            statement = (
                postgresql_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
                .returning(table.c.event_id)
            )
            return connection.execute(statement).scalar_one_or_none() is not None
        if dialect == "sqlite":
            statement = (
                sqlite_insert(table)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["event_id"])
            )
            return connection.execute(statement).rowcount == 1

        existing = connection.execute(
            select(TelemetrySample.id).where(
                TelemetrySample.event_id == values["event_id"]
            )
        ).first()
        if existing is not None:
            return False
        connection.execute(table.insert().values(**values))
        return True


def resolve_telemetry_context(
    connection: Connection,
    event: TelemetryEvent,
) -> ResolvedTelemetryContext | None:
    binding_rows = list(
        connection.execute(
            select(
                SessionChannelBinding.id,
                SessionChannelBinding.session_id,
            )
            .where(
                SessionChannelBinding.node_id == event.node_id,
                SessionChannelBinding.equipment_id == event.equipment_id,
                SessionChannelBinding.channel_id == event.channel_id,
                SessionChannelBinding.metric == event.metric,
                SessionChannelBinding.activated_at.is_not(None),
                SessionChannelBinding.activated_at <= event.captured_at,
                or_(
                    SessionChannelBinding.released_at.is_(None),
                    event.captured_at < SessionChannelBinding.released_at,
                ),
            )
            .order_by(
                SessionChannelBinding.activated_at.desc(),
                SessionChannelBinding.id.desc(),
            )
            .limit(2)
        ).mappings()
    )
    if not binding_rows:
        return None
    if len(binding_rows) > 1:
        raise TelemetryAttributionError(
            "telemetry identity resolves to multiple session bindings"
        )

    binding = binding_rows[0]
    session_id = str(binding["session_id"])
    snapshot_id = connection.execute(
        select(SessionConfigSnapshot.id)
        .where(
            SessionConfigSnapshot.session_id == session_id,
            SessionConfigSnapshot.captured_at <= event.captured_at,
        )
        .order_by(
            SessionConfigSnapshot.captured_at.desc(),
            SessionConfigSnapshot.version.desc(),
            SessionConfigSnapshot.id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    if snapshot_id is None:
        raise TelemetryAttributionError(
            "active session binding has no configuration snapshot at capture time"
        )

    stage_rows = list(
        connection.execute(
            select(SessionStage.id)
            .where(
                SessionStage.session_id == session_id,
                SessionStage.entered_at.is_not(None),
                SessionStage.entered_at <= event.captured_at,
                or_(
                    SessionStage.exited_at.is_(None),
                    event.captured_at < SessionStage.exited_at,
                ),
            )
            .order_by(SessionStage.entered_at.desc(), SessionStage.id.desc())
            .limit(2)
        ).scalars()
    )
    if len(stage_rows) > 1:
        raise TelemetryAttributionError(
            "telemetry capture time resolves to multiple active session stages"
        )

    return ResolvedTelemetryContext(
        session_id=session_id,
        stage_id=str(stage_rows[0]) if stage_rows else None,
        binding_id=str(binding["id"]),
        config_snapshot_id=str(snapshot_id),
    )


def _attributed_sample_select() -> Any:
    sample = TelemetrySample.__table__
    context = TelemetrySessionContext.__table__
    return select(
        sample.c.event_id,
        sample.c.node_id,
        sample.c.captured_at,
        sample.c.metric,
        sample.c.value,
        sample.c.unit,
        sample.c.quality,
        sample.c.source,
        sample.c.equipment_id,
        sample.c.channel_id,
        sample.c.alarm,
        sample.c.raw_value,
        sample.c.raw_status,
        sample.c.received_at,
        context.c.session_id,
        context.c.stage_id,
        context.c.binding_id,
        context.c.config_snapshot_id,
        context.c.resolver_version,
    ).select_from(
        sample.join(context, sample.c.event_id == context.c.telemetry_event_id)
    )


def _apply_session_filters(
    statement: Any,
    *,
    session_id: str,
    query: SessionTelemetryQuery,
) -> Any:
    sample = TelemetrySample.__table__
    context = TelemetrySessionContext.__table__
    filters = [context.c.session_id == session_id]
    if query.stage_id is not None:
        filters.append(context.c.stage_id == query.stage_id)
    telemetry_query = TelemetryQuery(
        node_id=query.node_id,
        equipment_id=query.equipment_id,
        channel_id=query.channel_id,
        metric=query.metric,
        quality=query.quality,
        alarm=query.alarm,
        from_at=query.from_at,
        to_at=query.to_at,
    )
    if telemetry_query.node_id is not None:
        filters.append(sample.c.node_id == telemetry_query.node_id)
    if telemetry_query.equipment_id is not None:
        filters.append(sample.c.equipment_id == telemetry_query.equipment_id)
    if telemetry_query.channel_id is not None:
        filters.append(sample.c.channel_id == telemetry_query.channel_id)
    if telemetry_query.metric is not None:
        filters.append(sample.c.metric == telemetry_query.metric)
    if telemetry_query.quality is not None:
        filters.append(sample.c.quality == telemetry_query.quality)
    if telemetry_query.alarm is not None:
        filters.append(sample.c.alarm == telemetry_query.alarm)
    if telemetry_query.from_at is not None:
        filters.append(sample.c.captured_at >= telemetry_query.from_at)
    if telemetry_query.to_at is not None:
        filters.append(sample.c.captured_at < telemetry_query.to_at)
    return statement.where(*filters)
