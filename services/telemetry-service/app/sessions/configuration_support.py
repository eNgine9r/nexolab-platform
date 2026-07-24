from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sessions.configuration_schemas import ConfigurationCommand
from app.sessions.domain import SessionDomainError, SessionState
from app.sessions.models import (
    AuditLog,
    SessionChannelBinding,
    SessionConfigSnapshot,
    SessionEvent,
    SessionLimit,
    TestSession,
)
from app.sessions.production_contract import (
    EXPECTED_PRODUCTION_SERIES_COUNT,
    PRODUCTION_IDENTITIES,
)
from app.sessions.repository import (
    SessionConflictError,
    SessionNotFoundError,
)


ACTIVE_STATES = frozenset({SessionState.RUNNING, SessionState.PAUSED})
TERMINAL_STATES = frozenset(
    {
        SessionState.COMPLETED,
        SessionState.CANCELLED,
        SessionState.ARCHIVED,
    }
)


@dataclass(frozen=True, slots=True)
class BindingMutationResult:
    binding: SessionChannelBinding
    event: SessionEvent
    replayed: bool
    active_config_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class ProductionBindingsResult:
    bindings: list[SessionChannelBinding]
    event: SessionEvent
    replayed: bool
    active_config_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class BindingRemovalResult:
    binding_id: str
    event: SessionEvent
    replayed: bool
    active_config_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class LimitSetMutationResult:
    version: int
    limits: list[SessionLimit]
    event: SessionEvent
    replayed: bool
    active_config_snapshot_id: str | None


@dataclass(frozen=True, slots=True)
class SessionConfigurationResult:
    session: TestSession
    bindings: list[SessionChannelBinding]
    active_limits: list[SessionLimit]
    active_snapshot: SessionConfigSnapshot | None
    snapshots: list[SessionConfigSnapshot]


class ConfigurationSupportMixin:
    _engine: Any

    def configuration(self, session_id: str) -> SessionConfigurationResult:
        with Session(self._engine, expire_on_commit=False) as db_session:
            record = self._require_session(db_session, session_id)
            bindings = self._bindings_for_session(
                db_session,
                session_id,
                include_released=True,
            )
            active_limits = (
                self._limits_for_version(
                    db_session,
                    session_id,
                    record.active_limit_version,
                )
                if record.active_limit_version is not None
                else []
            )
            snapshots = list(
                db_session.scalars(
                    select(SessionConfigSnapshot)
                    .where(SessionConfigSnapshot.session_id == session_id)
                    .order_by(SessionConfigSnapshot.version.asc())
                )
            )
            active_snapshot = next(
                (
                    item
                    for item in snapshots
                    if item.id == record.active_config_snapshot_id
                ),
                None,
            )
            for item in [record, *bindings, *active_limits, *snapshots]:
                db_session.expunge(item)
            return SessionConfigurationResult(
                session=record,
                bindings=bindings,
                active_limits=active_limits,
                active_snapshot=active_snapshot,
                snapshots=snapshots,
            )

    def _freeze_configuration(
        self,
        db_session: Session,
        record: TestSession,
        *,
        actor_id: str,
        captured_at: datetime,
        source: str,
    ) -> SessionConfigSnapshot:
        bindings = self._bindings_for_session(
            db_session,
            record.id,
            include_released=False,
        )
        limits = (
            self._limits_for_version(
                db_session,
                record.id,
                record.active_limit_version,
            )
            if record.active_limit_version is not None
            else []
        )
        identities = {
            (item.node_id, item.equipment_id, item.channel_id, item.metric)
            for item in bindings
        }
        payload = {
            "schema_version": 1,
            "session_id": record.id,
            "session_number": record.session_number,
            "node_id": record.node_id,
            "captured_at": captured_at.isoformat(),
            "bindings": [
                {
                    "id": item.id,
                    "node_id": item.node_id,
                    "equipment_id": item.equipment_id,
                    "channel_id": item.channel_id,
                    "metric": item.metric,
                    "unit": item.unit,
                    "metadata": item.binding_metadata,
                }
                for item in bindings
            ],
            "active_limit_version": record.active_limit_version,
            "limits": [
                {
                    "id": item.id,
                    "binding_id": item.binding_id,
                    "metric": item.metric,
                    "unit": item.unit,
                    "version": item.version,
                    "lower_limit": item.lower_limit,
                    "upper_limit": item.upper_limit,
                    "hysteresis": item.hysteresis,
                    "duration_seconds": item.duration_seconds,
                    "payload": item.payload,
                }
                for item in limits
            ],
            "sampling_policy": {
                "source": "device-agent",
                "expected_cycle_series": EXPECTED_PRODUCTION_SERIES_COUNT,
                "telemetry_continues_when_paused": True,
            },
            "equipment_profiles": {
                "xjp60d": "xjp60d-probe-map-v1",
                "le01mp": "le01mp-validated-register-subset-v1",
            },
            "production_contract": {
                "expected_series_count": EXPECTED_PRODUCTION_SERIES_COUNT,
                "bound_series_count": len(bindings),
                "complete": identities == PRODUCTION_IDENTITIES,
            },
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        version = int(
            db_session.scalar(
                select(func.max(SessionConfigSnapshot.version)).where(
                    SessionConfigSnapshot.session_id == record.id
                )
            )
            or 0
        ) + 1
        snapshot = SessionConfigSnapshot(
            id=str(uuid4()),
            session_id=record.id,
            version=version,
            source=source,
            payload=payload,
            content_sha256=hashlib.sha256(canonical).hexdigest(),
            created_by=actor_id,
            captured_at=captured_at,
            created_at=captured_at,
        )
        db_session.add(snapshot)
        db_session.flush()
        record.active_config_snapshot_id = snapshot.id
        return snapshot

    @staticmethod
    def _locked_session(db_session: Session, session_id: str) -> TestSession:
        record = db_session.scalar(
            select(TestSession)
            .where(TestSession.id == session_id)
            .with_for_update()
        )
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    @staticmethod
    def _require_session(db_session: Session, session_id: str) -> TestSession:
        record = db_session.get(TestSession, session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    @staticmethod
    def _event_by_key(
        db_session: Session,
        session_id: str,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent).where(
                SessionEvent.session_id == session_id,
                SessionEvent.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _assert_configuration_change_allowed(
        record: TestSession,
        command: ConfigurationCommand,
    ) -> SessionState:
        state = SessionState(record.state)
        if state in TERMINAL_STATES:
            raise SessionDomainError(
                "session_immutable",
                f"session configuration cannot be edited in {state.value} state",
                current_state=state,
            )
        if state in ACTIVE_STATES:
            if not command.allow_active_change or not command.reason:
                raise SessionConflictError(
                    "active_configuration_change_requires_ack",
                    "active session configuration changes require "
                    "allow_active_change=true and a reason",
                )
        return state

    @staticmethod
    def _bindings_for_session(
        db_session: Session,
        session_id: str,
        *,
        include_released: bool,
    ) -> list[SessionChannelBinding]:
        statement = select(SessionChannelBinding).where(
            SessionChannelBinding.session_id == session_id
        )
        if not include_released:
            statement = statement.where(SessionChannelBinding.released_at.is_(None))
        return list(
            db_session.scalars(
                statement.order_by(
                    SessionChannelBinding.equipment_id.asc(),
                    SessionChannelBinding.channel_id.asc(),
                    SessionChannelBinding.metric.asc(),
                )
            )
        )

    @staticmethod
    def _limits_for_version(
        db_session: Session,
        session_id: str,
        version: int,
    ) -> list[SessionLimit]:
        return list(
            db_session.scalars(
                select(SessionLimit)
                .where(
                    SessionLimit.session_id == session_id,
                    SessionLimit.version == version,
                )
                .order_by(
                    SessionLimit.binding_id.asc(),
                    SessionLimit.metric.asc(),
                    SessionLimit.id.asc(),
                )
            )
        )

    @staticmethod
    def _latest_limit_for_identity(
        db_session: Session,
        session_id: str,
        *,
        binding_id: str | None,
        metric: str,
    ) -> SessionLimit | None:
        statement = select(SessionLimit).where(
            SessionLimit.session_id == session_id,
            SessionLimit.metric == metric,
        )
        if binding_id is None:
            statement = statement.where(SessionLimit.binding_id.is_(None))
        else:
            statement = statement.where(SessionLimit.binding_id == binding_id)
        return db_session.scalar(
            statement.order_by(SessionLimit.version.desc()).limit(1)
        )

    @staticmethod
    def _configuration_event(
        record: TestSession,
        *,
        event_type: str,
        command: ConfigurationCommand,
        idempotency_key: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
    ) -> SessionEvent:
        return SessionEvent(
            id=str(uuid4()),
            session_id=record.id,
            event_type=event_type,
            previous_state=record.state,
            next_state=record.state,
            actor_id=command.actor_id,
            actor_source=command.actor_source,
            reason=command.reason,
            payload={
                **payload,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
            idempotency_key=idempotency_key,
            occurred_at=command.occurred_at,
            inserted_at=command.occurred_at,
        )

    @staticmethod
    def _audit_for_configuration_event(
        event: SessionEvent,
        *,
        entity_type: str,
        entity_id: str,
    ) -> AuditLog:
        return AuditLog(
            id=str(uuid4()),
            session_id=event.session_id,
            session_event_id=event.id,
            actor_id=event.actor_id,
            actor_source=event.actor_source,
            action=event.event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=event.payload,
            occurred_at=event.occurred_at,
            inserted_at=event.inserted_at,
        )

    @staticmethod
    def _detach_binding_result(
        db_session: Session,
        binding: SessionChannelBinding,
        event: SessionEvent,
        active_config_snapshot_id: str | None,
        *,
        replayed: bool,
    ) -> BindingMutationResult:
        db_session.expunge(binding)
        db_session.expunge(event)
        return BindingMutationResult(
            binding=binding,
            event=event,
            replayed=replayed,
            active_config_snapshot_id=active_config_snapshot_id,
        )

    @staticmethod
    def _detach_production_result(
        db_session: Session,
        bindings: list[SessionChannelBinding],
        event: SessionEvent,
        active_config_snapshot_id: str | None,
        *,
        replayed: bool,
    ) -> ProductionBindingsResult:
        for binding in bindings:
            db_session.expunge(binding)
        db_session.expunge(event)
        return ProductionBindingsResult(
            bindings=bindings,
            event=event,
            replayed=replayed,
            active_config_snapshot_id=active_config_snapshot_id,
        )

    @staticmethod
    def _detach_limit_result(
        db_session: Session,
        version: int,
        limits: list[SessionLimit],
        event: SessionEvent,
        active_config_snapshot_id: str | None,
        *,
        replayed: bool,
    ) -> LimitSetMutationResult:
        for item in limits:
            db_session.expunge(item)
        db_session.expunge(event)
        return LimitSetMutationResult(
            version=version,
            limits=limits,
            event=event,
            replayed=replayed,
            active_config_snapshot_id=active_config_snapshot_id,
        )
