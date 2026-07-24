from __future__ import annotations

from typing import Final


SESSION_MODEL_COUNT: Final = 9


def register_models() -> None:
    """Import persistence models so they are attached to Base.metadata."""
    from app.sessions import models as _session_models
    from app.sessions import telemetry_attribution as _telemetry_attribution
    from app.sessions.audit_immutability import register_audit_immutability

    register_audit_immutability()
    assert len(_session_models.SESSION_STATES) == 7
    assert _telemetry_attribution.TelemetrySessionContext.__tablename__ == (
        "telemetry_session_contexts"
    )
