from __future__ import annotations

from typing import Final


SESSION_MODEL_COUNT: Final = 9


def register_models() -> None:
    """Import persistence models so they are attached to Base.metadata."""
    from app.alerts import models as _alert_models
    from app.alerts.immutability import register_alert_immutability
    from app.nodes import models as _node_models
    from app.refrigeration import models as _refrigeration_models
    from app.reports import models as _report_models
    from app.reports.immutability import register_report_immutability
    from app.security import models as _security_models
    from app.sessions import models as _session_models
    from app.sessions import telemetry_attribution as _telemetry_attribution
    from app.sessions.audit_immutability import register_audit_immutability

    register_audit_immutability()
    register_alert_immutability()
    register_report_immutability()
    assert len(_session_models.SESSION_STATES) == 7
    assert _telemetry_attribution.TelemetrySessionContext.__tablename__ == (
        "telemetry_session_contexts"
    )
    assert _alert_models.AlertRule.__tablename__ == "alert_rules"
    assert _alert_models.AlertInstance.__tablename__ == "alert_instances"
    assert _node_models.CentralNode.__tablename__ == "central_nodes"
    assert _node_models.CentralNodeCredential.__tablename__ == (
        "central_node_credentials"
    )
    assert _node_models.CentralNodeIngressCursor.__tablename__ == (
        "central_node_ingress_cursors"
    )
    assert _node_models.CentralNodeHealthSample.__tablename__ == (
        "central_node_health_samples"
    )
    assert _node_models.CentralNodeStatusEvent.__tablename__ == (
        "central_node_status_events"
    )
    assert _refrigeration_models.RefrigerationLayoutDraft.__tablename__ == (
        "refrigeration_layout_drafts"
    )
    assert _report_models.TestReportVersion.__tablename__ == "test_report_versions"
    assert _report_models.TestReportArtifact.__tablename__ == "test_report_artifacts"
    assert _report_models.TestReportRender.__tablename__ == "test_report_renders"
    assert _report_models.TestReportApprovalEvent.__tablename__ == (
        "test_report_approval_events"
    )
    assert _security_models.SecurityAuditEvent.__tablename__ == "security_audit_events"
