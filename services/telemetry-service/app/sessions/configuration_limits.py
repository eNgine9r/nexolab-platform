from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.sessions.configuration_schemas import SessionLimitSetCreate
from app.sessions.configuration_support import (
    ACTIVE_STATES,
    LimitSetMutationResult,
)
from app.sessions.models import SessionChannelBinding, SessionLimit
from app.sessions.repository import SessionConflictError


class LimitRepositoryMixin:
    def add_limit_set(
        self,
        session_id: str,
        payload: SessionLimitSetCreate,
        *,
        idempotency_key: str,
    ) -> LimitSetMutationResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            with db_session.begin():
                record = self._locked_session(db_session, session_id)
                existing_event = self._event_by_key(
                    db_session,
                    session_id,
                    normalized_key,
                )
                if existing_event is not None:
                    if existing_event.event_type != "session_limit_version_created":
                        raise SessionConflictError(
                            "idempotency_key_reused",
                            "Idempotency-Key was used for another session command",
                        )
                    version = int(existing_event.payload["version"])
                    limits = self._limits_for_version(
                        db_session,
                        session_id,
                        version,
                    )
                    return self._detach_limit_result(
                        db_session,
                        version,
                        limits,
                        existing_event,
                        existing_event.payload.get("config_snapshot_id"),
                        replayed=True,
                    )

                state = self._assert_configuration_change_allowed(record, payload)
                binding_ids = {
                    item.binding_id
                    for item in payload.limits
                    if item.binding_id is not None
                }
                if binding_ids:
                    valid_binding_ids = set(
                        db_session.scalars(
                            select(SessionChannelBinding.id).where(
                                SessionChannelBinding.session_id == session_id,
                                SessionChannelBinding.id.in_(binding_ids),
                                SessionChannelBinding.released_at.is_(None),
                            )
                        )
                    )
                    if binding_ids - valid_binding_ids:
                        raise SessionConflictError(
                            "limit_binding_not_found",
                            "one or more limit bindings are not active "
                            "in this session",
                        )

                version = int(
                    db_session.scalar(
                        select(func.max(SessionLimit.version)).where(
                            SessionLimit.session_id == session_id
                        )
                    )
                    or 0
                ) + 1
                limits: list[SessionLimit] = []
                for rule in payload.limits:
                    previous = self._latest_limit_for_identity(
                        db_session,
                        session_id,
                        binding_id=rule.binding_id,
                        metric=rule.metric,
                    )
                    item = SessionLimit(
                        id=str(uuid4()),
                        session_id=session_id,
                        binding_id=rule.binding_id,
                        config_snapshot_id=None,
                        supersedes_limit_id=previous.id if previous else None,
                        metric=rule.metric,
                        unit=rule.unit,
                        version=version,
                        lower_limit=rule.lower_limit,
                        upper_limit=rule.upper_limit,
                        hysteresis=rule.hysteresis,
                        duration_seconds=rule.duration_seconds,
                        payload=rule.payload,
                        created_by=payload.actor_id,
                        effective_at=payload.occurred_at,
                        created_at=payload.occurred_at,
                    )
                    db_session.add(item)
                    limits.append(item)

                record.active_limit_version = version
                db_session.flush()
                snapshot = None
                if state in ACTIVE_STATES:
                    snapshot = self._freeze_configuration(
                        db_session,
                        record,
                        actor_id=payload.actor_id,
                        captured_at=payload.occurred_at,
                        source="active_limit_change",
                    )
                    for item in limits:
                        item.config_snapshot_id = snapshot.id

                event = self._configuration_event(
                    record,
                    event_type="session_limit_version_created",
                    command=payload,
                    idempotency_key=normalized_key,
                    entity_type="session_limit_set",
                    entity_id=f"{session_id}:{version}",
                    payload={
                        "version": version,
                        "limit_ids": [item.id for item in limits],
                        "config_snapshot_id": snapshot.id if snapshot else None,
                    },
                )
                audit = self._audit_for_configuration_event(
                    event,
                    entity_type="session_limit_set",
                    entity_id=f"{session_id}:{version}",
                )
                db_session.add_all([event, audit])
                record.lock_version += 1
                record.updated_at = payload.occurred_at
                db_session.flush()

            return self._detach_limit_result(
                db_session,
                version,
                limits,
                event,
                record.active_config_snapshot_id,
                replayed=False,
            )

    def limits(
        self,
        session_id: str,
        *,
        version: int | None,
    ) -> list[SessionLimit]:
        with Session(self._engine, expire_on_commit=False) as db_session:
            record = self._require_session(db_session, session_id)
            resolved_version = (
                version if version is not None else record.active_limit_version
            )
            if resolved_version is None:
                return []
            items = self._limits_for_version(
                db_session,
                session_id,
                resolved_version,
            )
            for item in items:
                db_session.expunge(item)
            return items
