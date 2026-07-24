from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Connection, or_, select

from app.contracts import TelemetryEvent
from app.sessions.models import (
    SessionChannelBinding,
    SessionConfigSnapshot,
    SessionEvent,
    SessionStageTransition,
    TestSession,
)
from app.sessions.telemetry_context import TelemetryAttribution


ATTRIBUTABLE_STATES = frozenset({"running", "paused"})


class ActiveSessionResolver:
    """Resolve immutable session context at the telemetry capture boundary."""

    def resolve(
        self,
        connection: Connection,
        event: TelemetryEvent,
    ) -> TelemetryAttribution | None:
        captured_at = event.captured_at
        candidate = connection.execute(
            select(
                SessionChannelBinding.id.label("binding_id"),
                SessionChannelBinding.session_id.label("session_id"),
            )
            .join(
                TestSession,
                TestSession.id == SessionChannelBinding.session_id,
            )
            .where(
                SessionChannelBinding.node_id == event.node_id,
                SessionChannelBinding.equipment_id == event.equipment_id,
                SessionChannelBinding.channel_id == event.channel_id,
                SessionChannelBinding.metric == event.metric,
                SessionChannelBinding.activated_at.is_not(None),
                SessionChannelBinding.activated_at <= captured_at,
                or_(
                    SessionChannelBinding.released_at.is_(None),
                    captured_at < SessionChannelBinding.released_at,
                ),
                TestSession.started_at.is_not(None),
                TestSession.started_at <= captured_at,
                or_(
                    TestSession.completed_at.is_(None),
                    captured_at < TestSession.completed_at,
                ),
                or_(
                    TestSession.cancelled_at.is_(None),
                    captured_at < TestSession.cancelled_at,
                ),
            )
            .order_by(
                SessionChannelBinding.activated_at.desc(),
                SessionChannelBinding.id.asc(),
            )
            .limit(1)
        ).mappings().first()
        if candidate is None:
            return None

        session_id = str(candidate["session_id"])
        state = connection.scalar(
            select(SessionEvent.next_state)
            .where(
                SessionEvent.session_id == session_id,
                SessionEvent.occurred_at <= captured_at,
                SessionEvent.next_state.is_not(None),
            )
            .order_by(
                SessionEvent.occurred_at.desc(),
                SessionEvent.inserted_at.desc(),
                SessionEvent.id.desc(),
            )
            .limit(1)
        )
        if state not in ATTRIBUTABLE_STATES:
            return None

        config_snapshot_id = connection.scalar(
            select(SessionConfigSnapshot.id)
            .where(
                SessionConfigSnapshot.session_id == session_id,
                SessionConfigSnapshot.captured_at <= captured_at,
            )
            .order_by(
                SessionConfigSnapshot.captured_at.desc(),
                SessionConfigSnapshot.version.desc(),
                SessionConfigSnapshot.id.desc(),
            )
            .limit(1)
        )
        if config_snapshot_id is None:
            return None

        stage_id = connection.scalar(
            select(SessionStageTransition.to_stage_id)
            .where(
                SessionStageTransition.session_id == session_id,
                SessionStageTransition.occurred_at <= captured_at,
            )
            .order_by(
                SessionStageTransition.occurred_at.desc(),
                SessionStageTransition.inserted_at.desc(),
                SessionStageTransition.id.desc(),
            )
            .limit(1)
        )

        return TelemetryAttribution(
            session_id=session_id,
            binding_id=str(candidate["binding_id"]),
            stage_id=str(stage_id) if stage_id is not None else None,
            config_snapshot_id=str(config_snapshot_id),
            session_state=str(state),
            captured_at=captured_at,
            attributed_at=datetime.now(UTC),
        )
