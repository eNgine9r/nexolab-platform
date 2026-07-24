from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection

from app.contracts import TelemetryEvent
from app.db import Database, TelemetryQuery, TelemetrySample
from app.sessions.telemetry_context import (
    TelemetryAttribution,
    TelemetrySessionContext,
)


AttributionResolver = Callable[
    [Connection, TelemetryEvent],
    TelemetryAttribution | None,
]


@dataclass(frozen=True)
class SessionTelemetryQuery(TelemetryQuery):
    session_id: str | None = None
    stage_id: str | None = None
    binding_id: str | None = None
    config_snapshot_id: str | None = None
    session_state: str | None = None


@dataclass(frozen=True)
class TelemetrySampleView:
    sample: TelemetrySample
    context: TelemetrySessionContext | None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.sample, name)

    @property
    def session_id(self) -> str | None:
        return self.context.session_id if self.context is not None else None

    @property
    def stage_id(self) -> str | None:
        return self.context.stage_id if self.context is not None else None

    @property
    def binding_id(self) -> str | None:
        return self.context.binding_id if self.context is not None else None

    @property
    def config_snapshot_id(self) -> str | None:
        return (
            self.context.config_snapshot_id if self.context is not None else None
        )

    @property
    def session_state(self) -> str | None:
        return self.context.session_state if self.context is not None else None


class SessionAwareDatabase(Database):
    def __init__(
        self,
        database_url: str,
        *,
        attribution_resolver: AttributionResolver,
        connect_timeout_seconds: int = 3,
    ) -> None:
        super().__init__(
            database_url,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        self._attribution_resolver = attribution_resolver

        if self.engine.dialect.name == "sqlite":

            @sqlalchemy_event.listens_for(self.engine, "connect")
            def enable_sqlite_foreign_keys(
                dbapi_connection: Any,
                _: Any,
            ) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

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
                inserted = connection.execute(statement).scalar_one_or_none()
                if inserted is None:
                    return False
            elif dialect == "sqlite":
                statement = (
                    sqlite_insert(table)
                    .values(**values)
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
                result = connection.execute(statement)
                if result.rowcount != 1:
                    return False
            else:
                existing = connection.execute(
                    select(TelemetrySample.id).where(
                        TelemetrySample.event_id == str(event.event_id)
                    )
                ).first()
                if existing is not None:
                    return False
                connection.execute(table.insert().values(**values))

            attribution = self._attribution_resolver(connection, event)
            if attribution is not None:
                connection.execute(
                    TelemetrySessionContext.__table__.insert().values(
                        event_id=str(event.event_id),
                        session_id=attribution.session_id,
                        binding_id=attribution.binding_id,
                        stage_id=attribution.stage_id,
                        config_snapshot_id=attribution.config_snapshot_id,
                        session_state=attribution.session_state,
                        captured_at=attribution.captured_at,
                        attributed_at=attribution.attributed_at,
                    )
                )
        return True

    @staticmethod
    def _apply_context_filters(
        statement: Any,
        query: SessionTelemetryQuery,
    ) -> Any:
        filters = []
        if query.session_id is not None:
            filters.append(TelemetrySessionContext.session_id == query.session_id)
        if query.stage_id is not None:
            filters.append(TelemetrySessionContext.stage_id == query.stage_id)
        if query.binding_id is not None:
            filters.append(TelemetrySessionContext.binding_id == query.binding_id)
        if query.config_snapshot_id is not None:
            filters.append(
                TelemetrySessionContext.config_snapshot_id
                == query.config_snapshot_id
            )
        if query.session_state is not None:
            filters.append(
                TelemetrySessionContext.session_state == query.session_state
            )
        if filters:
            statement = statement.join(
                TelemetrySessionContext,
                TelemetrySessionContext.event_id == TelemetrySample.event_id,
            ).where(*filters)
        return statement

    @staticmethod
    def _view_rows(rows: list[Any]) -> list[TelemetrySampleView]:
        return [
            TelemetrySampleView(sample=row[0], context=row[1])
            for row in rows
        ]

    def latest_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetrySampleView]:
        session_query = (
            query
            if isinstance(query, SessionTelemetryQuery)
            else SessionTelemetryQuery(**query.__dict__)
        )
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
        ranked_statement = Database._apply_filters(ranked_statement, session_query)
        ranked_statement = self._apply_context_filters(
            ranked_statement,
            session_query,
        )
        ranked = ranked_statement.subquery()

        statement = (
            select(TelemetrySample, TelemetrySessionContext)
            .join(ranked, TelemetrySample.id == ranked.c.sample_id)
            .outerjoin(
                TelemetrySessionContext,
                TelemetrySessionContext.event_id == TelemetrySample.event_id,
            )
            .where(ranked.c.sample_rank == 1)
            .order_by(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._sessions() as session:
            return self._view_rows(list(session.execute(statement).all()))

    def history_samples(
        self,
        *,
        query: TelemetryQuery,
        limit: int,
        offset: int,
    ) -> list[TelemetrySampleView]:
        session_query = (
            query
            if isinstance(query, SessionTelemetryQuery)
            else SessionTelemetryQuery(**query.__dict__)
        )
        statement = select(TelemetrySample)
        statement = Database._apply_filters(statement, session_query)
        statement = self._apply_context_filters(statement, session_query)
        sample_ids = statement.with_only_columns(TelemetrySample.id).subquery()
        result_statement = (
            select(TelemetrySample, TelemetrySessionContext)
            .join(sample_ids, TelemetrySample.id == sample_ids.c.id)
            .outerjoin(
                TelemetrySessionContext,
                TelemetrySessionContext.event_id == TelemetrySample.event_id,
            )
            .order_by(
                TelemetrySample.captured_at.desc(),
                TelemetrySample.event_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        with self._sessions() as session:
            return self._view_rows(list(session.execute(result_statement).all()))

    def context_payload(self, event_id: str) -> dict[str, Any] | None:
        with self._sessions() as session:
            context = session.get(TelemetrySessionContext, event_id)
            if context is None:
                return None
            return {
                "session_id": context.session_id,
                "stage_id": context.stage_id,
                "binding_id": context.binding_id,
                "config_snapshot_id": context.config_snapshot_id,
                "session_state": context.session_state,
            }

    def count_attributed_samples(self, session_id: str | None = None) -> int:
        statement = select(func.count()).select_from(TelemetrySessionContext)
        if session_id is not None:
            statement = statement.where(
                TelemetrySessionContext.session_id == session_id
            )
        with self._sessions() as session:
            return int(session.scalar(statement) or 0)
