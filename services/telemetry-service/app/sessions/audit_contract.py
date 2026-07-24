from __future__ import annotations

from typing import Final


ALLOWED_ACTOR_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "dashboard",
        "api",
        "automation",
        "system",
        "import",
    }
)

CANONICAL_AUDIT_ACTIONS: Final[dict[str, str]] = {
    "session_created": "session_created",
    "session_binding_added": "channel_assigned",
    "production_bindings_applied": "channel_assigned",
    "session_binding_removed": "channel_removed",
    "session_limit_version_created": "limit_version_created",
    "session_prepared": "session_prepared",
    "session_started": "session_started",
    "session_paused": "session_paused",
    "session_resumed": "session_resumed",
    "session_stage_advanced": "stage_changed",
    "note_added": "note_added",
    "session_completed": "session_completed",
    "session_cancelled": "session_cancelled",
    "session_archived": "session_archived",
}


def canonical_audit_action(action: str) -> str:
    return CANONICAL_AUDIT_ACTIONS.get(action, action)


def validate_actor_source(value: str) -> str:
    normalized = value.strip()
    if normalized not in ALLOWED_ACTOR_SOURCES:
        allowed = ", ".join(sorted(ALLOWED_ACTOR_SOURCES))
        raise ValueError(f"actor_source must be one of: {allowed}")
    return normalized
