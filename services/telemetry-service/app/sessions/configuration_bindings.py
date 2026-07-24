from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.sessions.configuration_schemas import (
    ProductionBindingsCreate,
    SessionBindingCreate,
    SessionBindingRemove,
)
from app.sessions.configuration_support import (
    ACTIVE_STATES,
    BindingMutationResult,
    BindingRemovalResult,
    ProductionBindingsResult,
)
from app.sessions.models import SessionChannelBinding
from app.sessions.production_contract import (
    EXPECTED_PRODUCTION_SERIES_COUNT,
    PRODUCTION_CHANNEL_BY_IDENTITY,
    PRODUCTION_CHANNELS,
)
from app.sessions.repository import SessionConflictError


class BindingRepositoryMixin:
    def add_binding(
        self,
        session_id: str,
        payload: SessionBindingCreate,
        *,
        idempotency_key: str,
    ) -> BindingMutationResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)
        identity = (
            payload.node_id,
            payload.equipment_id,
            payload.channel_id,
            payload.metric,
        )
        specification = PRODUCTION_CHANNEL_BY_IDENTITY.get(identity)
        if specification is None:
            raise SessionConflictError(
                "unknown_production_channel",
                "binding does not match the validated production channel contract",
            )
        if payload.unit is not None and payload.unit != specification.unit:
            raise SessionConflictError(
                "binding_unit_mismatch",
                f"channel {payload.channel_id!r} requires unit {specification.unit!r}",
            )

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    record = self._locked_session(db_session, session_id)
                    existing_event = self._event_by_key(
                        db_session,
                        session_id,
                        normalized_key,
                    )
                    if existing_event is not None:
                        if existing_event.event_type != "session_binding_added":
                            raise SessionConflictError(
                                "idempotency_key_reused",
                                "Idempotency-Key was used for another session command",
                            )
                        binding_id = str(existing_event.payload["binding_id"])
                        binding = db_session.get(SessionChannelBinding, binding_id)
                        if binding is None:
                            raise SessionConflictError(
                                "binding_replay_conflict",
                                "idempotent binding result is no longer available",
                            )
                        return self._detach_binding_result(
                            db_session,
                            binding,
                            existing_event,
                            existing_event.payload.get("config_snapshot_id"),
                            replayed=True,
                        )

                    state = self._assert_configuration_change_allowed(record, payload)
                    duplicate = db_session.scalar(
                        select(SessionChannelBinding).where(
                            SessionChannelBinding.session_id == session_id,
                            SessionChannelBinding.node_id == payload.node_id,
                            SessionChannelBinding.equipment_id == payload.equipment_id,
                            SessionChannelBinding.channel_id == payload.channel_id,
                            SessionChannelBinding.metric == payload.metric,
                        )
                    )
                    if duplicate is not None:
                        raise SessionConflictError(
                            "duplicate_session_binding",
                            "the channel is already bound to this session",
                        )

                    binding = SessionChannelBinding(
                        id=str(uuid4()),
                        session_id=session_id,
                        node_id=payload.node_id,
                        equipment_id=payload.equipment_id,
                        channel_id=payload.channel_id,
                        metric=payload.metric,
                        unit=specification.unit,
                        binding_metadata={
                            **payload.binding_metadata,
                            **specification.metadata,
                        },
                        activated_at=(
                            payload.occurred_at if state in ACTIVE_STATES else None
                        ),
                        released_at=None,
                        created_at=payload.occurred_at,
                    )
                    db_session.add(binding)
                    db_session.flush()

                    snapshot = None
                    if state in ACTIVE_STATES:
                        snapshot = self._freeze_configuration(
                            db_session,
                            record,
                            actor_id=payload.actor_id,
                            captured_at=payload.occurred_at,
                            source="active_binding_change",
                        )

                    event = self._configuration_event(
                        record,
                        event_type="session_binding_added",
                        command=payload,
                        idempotency_key=normalized_key,
                        entity_type="session_channel_binding",
                        entity_id=binding.id,
                        payload={
                            "binding_id": binding.id,
                            "identity": list(identity),
                            "config_snapshot_id": snapshot.id if snapshot else None,
                        },
                    )
                    audit = self._audit_for_configuration_event(
                        event,
                        entity_type="session_channel_binding",
                        entity_id=binding.id,
                    )
                    db_session.add_all([event, audit])
                    record.lock_version += 1
                    record.updated_at = payload.occurred_at
                    db_session.flush()

                return self._detach_binding_result(
                    db_session,
                    binding,
                    event,
                    record.active_config_snapshot_id,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                raise SessionConflictError(
                    "active_channel_lease_conflict",
                    "the channel is already leased by another active session",
                ) from error

    def add_production_bindings(
        self,
        session_id: str,
        payload: ProductionBindingsCreate,
        *,
        idempotency_key: str,
    ) -> ProductionBindingsResult:
        normalized_key = self._normalize_idempotency_key(idempotency_key)

        with Session(self._engine, expire_on_commit=False) as db_session:
            try:
                with db_session.begin():
                    record = self._locked_session(db_session, session_id)
                    existing_event = self._event_by_key(
                        db_session,
                        session_id,
                        normalized_key,
                    )
                    if existing_event is not None:
                        if existing_event.event_type != "production_bindings_applied":
                            raise SessionConflictError(
                                "idempotency_key_reused",
                                "Idempotency-Key was used for another session command",
                            )
                        bindings = self._bindings_for_session(
                            db_session,
                            session_id,
                            include_released=False,
                        )
                        return self._detach_production_result(
                            db_session,
                            bindings,
                            existing_event,
                            existing_event.payload.get("config_snapshot_id"),
                            replayed=True,
                        )

                    state = self._assert_configuration_change_allowed(record, payload)
                    existing_identities = {
                        (
                            item.node_id,
                            item.equipment_id,
                            item.channel_id,
                            item.metric,
                        )
                        for item in self._bindings_for_session(
                            db_session,
                            session_id,
                            include_released=True,
                        )
                    }
                    added_ids: list[str] = []
                    for specification in PRODUCTION_CHANNELS:
                        if specification.identity in existing_identities:
                            continue
                        binding = SessionChannelBinding(
                            id=str(uuid4()),
                            session_id=session_id,
                            node_id=specification.node_id,
                            equipment_id=specification.equipment_id,
                            channel_id=specification.channel_id,
                            metric=specification.metric,
                            unit=specification.unit,
                            binding_metadata={
                                **payload.binding_metadata,
                                **specification.metadata,
                            },
                            activated_at=(
                                payload.occurred_at
                                if state in ACTIVE_STATES
                                else None
                            ),
                            released_at=None,
                            created_at=payload.occurred_at,
                        )
                        db_session.add(binding)
                        added_ids.append(binding.id)
                    db_session.flush()

                    snapshot = None
                    if state in ACTIVE_STATES:
                        snapshot = self._freeze_configuration(
                            db_session,
                            record,
                            actor_id=payload.actor_id,
                            captured_at=payload.occurred_at,
                            source="active_binding_change",
                        )

                    bindings = self._bindings_for_session(
                        db_session,
                        session_id,
                        include_released=False,
                    )
                    event = self._configuration_event(
                        record,
                        event_type="production_bindings_applied",
                        command=payload,
                        idempotency_key=normalized_key,
                        entity_type="test_session",
                        entity_id=session_id,
                        payload={
                            "added_binding_ids": added_ids,
                            "binding_count": len(bindings),
                            "expected_series_count": (
                                EXPECTED_PRODUCTION_SERIES_COUNT
                            ),
                            "config_snapshot_id": snapshot.id if snapshot else None,
                        },
                    )
                    audit = self._audit_for_configuration_event(
                        event,
                        entity_type="test_session",
                        entity_id=session_id,
                    )
                    db_session.add_all([event, audit])
                    record.lock_version += 1
                    record.updated_at = payload.occurred_at
                    db_session.flush()

                return self._detach_production_result(
                    db_session,
                    bindings,
                    event,
                    record.active_config_snapshot_id,
                    replayed=False,
                )
            except IntegrityError as error:
                db_session.rollback()
                raise SessionConflictError(
                    "active_channel_lease_conflict",
                    "one or more production channels are leased "
                    "by another active session",
                ) from error

    def remove_binding(
        self,
        session_id: str,
        binding_id: str,
        payload: SessionBindingRemove,
        *,
        idempotency_key: str,
    ) -> BindingRemovalResult:
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
                    if existing_event.event_type != "session_binding_removed":
                        raise SessionConflictError(
                            "idempotency_key_reused",
                            "Idempotency-Key was used for another session command",
                        )
                    replay_binding_id = str(existing_event.payload["binding_id"])
                    snapshot_id = existing_event.payload.get("config_snapshot_id")
                    db_session.expunge(existing_event)
                    db_session.expunge(record)
                    return BindingRemovalResult(
                        binding_id=replay_binding_id,
                        event=existing_event,
                        replayed=True,
                        active_config_snapshot_id=snapshot_id,
                    )

                state = self._assert_configuration_change_allowed(record, payload)
                binding = db_session.scalar(
                    select(SessionChannelBinding)
                    .where(
                        SessionChannelBinding.id == binding_id,
                        SessionChannelBinding.session_id == session_id,
                    )
                    .with_for_update()
                )
                if binding is None:
                    raise SessionConflictError(
                        "session_binding_not_found",
                        f"binding {binding_id!r} was not found in the session",
                    )
                if binding.released_at is not None:
                    raise SessionConflictError(
                        "session_binding_already_removed",
                        "binding has already been removed",
                    )

                snapshot = None
                if state in ACTIVE_STATES:
                    if (
                        binding.activated_at is not None
                        and payload.occurred_at < binding.activated_at
                    ):
                        raise SessionConflictError(
                            "binding_release_time_invalid",
                            "binding removal cannot precede activation",
                        )
                    binding.released_at = payload.occurred_at
                    db_session.flush()
                    snapshot = self._freeze_configuration(
                        db_session,
                        record,
                        actor_id=payload.actor_id,
                        captured_at=payload.occurred_at,
                        source="active_binding_change",
                    )
                else:
                    db_session.delete(binding)
                    db_session.flush()

                event = self._configuration_event(
                    record,
                    event_type="session_binding_removed",
                    command=payload,
                    idempotency_key=normalized_key,
                    entity_type="session_channel_binding",
                    entity_id=binding_id,
                    payload={
                        "binding_id": binding_id,
                        "config_snapshot_id": snapshot.id if snapshot else None,
                    },
                )
                audit = self._audit_for_configuration_event(
                    event,
                    entity_type="session_channel_binding",
                    entity_id=binding_id,
                )
                db_session.add_all([event, audit])
                record.lock_version += 1
                record.updated_at = payload.occurred_at
                db_session.flush()

            db_session.expunge(event)
            db_session.expunge(record)
            return BindingRemovalResult(
                binding_id=binding_id,
                event=event,
                replayed=False,
                active_config_snapshot_id=record.active_config_snapshot_id,
            )

    def bindings(
        self,
        session_id: str,
        *,
        include_released: bool,
    ) -> list[SessionChannelBinding]:
        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)
            items = self._bindings_for_session(
                db_session,
                session_id,
                include_released=include_released,
            )
            for item in items:
                db_session.expunge(item)
            return items
