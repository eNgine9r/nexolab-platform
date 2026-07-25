from __future__ import annotations

from typing import Final


SESSION_MODEL_COUNT: Final = 9


def register_models() -> None:
    """Import persistence models so they are attached to Base.metadata."""
    from app.alerts import models as _alert_models
    from app.refrigeration import models as _refrigeration_models
    from app.security import models as _security_models
    from app.sessions import models as _session_models
    from app.sessions import telemetry_attribution as _telemetry_attribution
    from app.sessions.audit_immutability import register_audit_immutability

    register_audit_immutability()
    assert len(_session_models.SESSION_STATES) == 7
    assert _telemetry_attribution.TelemetrySessionContext.__tablename__ == (
        "telemetry_session_contexts"
    )
    assert _refrigeration_models.RefrigerationLayoutDraft.__tablename__ == (
        "refrigeration_layout_drafts"
    )
    assert _security_models.SecurityAuditEvent.__tablename__ == "security_audit_events"
    assert _alert_models.AlertRuleModel.__tablename__ == "alert_rules"
    assert _alert_models.AlertModel.__tablename__ == "alerts"
    assert _alert_models.AlertEventModel.__tablename__ == "alert_events"
