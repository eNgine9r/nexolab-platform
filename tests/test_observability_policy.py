from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "scripts/validate-observability.py"
SPEC = importlib.util.spec_from_file_location("validate_observability", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def write_yaml(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def alert_rules() -> dict[str, dict[str, object]]:
    source = ROOT / "infrastructure/observability/prometheus/rules/nexolab-platform.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    group = next(
        item for item in payload["groups"] if item["name"] == "nexolab-platform-alerts"
    )
    return {rule["alert"]: rule for rule in group["rules"] if "alert" in rule}


def matcher_value(matcher: str, label: str) -> str | None:
    prefix = f'{label}="'
    return matcher[len(prefix) : -1] if matcher.startswith(prefix) and matcher.endswith('"') else None


def test_repository_observability_policy_is_valid() -> None:
    validator.validate_repository(ROOT)


def test_compose_rejects_latest_image(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/compose/compose.observability.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["services"]["prometheus"]["image"] = "prom/prometheus:latest"
    path = tmp_path / "compose.yaml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="must pin"):
        validator.validate_compose(path)


def test_compose_rejects_public_default_bind(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/compose/compose.observability.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["services"]["grafana"]["ports"] = ["0.0.0.0:3000:3000"]
    path = tmp_path / "compose.yaml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="loopback"):
        validator.validate_compose(path)


def test_acceptance_resources_are_namespaced_by_compose_project() -> None:
    central = yaml.safe_load(
        (ROOT / "infrastructure/compose/compose.central.yaml").read_text(encoding="utf-8")
    )
    observability = yaml.safe_load(
        (ROOT / "infrastructure/compose/compose.observability.yaml").read_text(
            encoding="utf-8"
        )
    )

    central_prefix = "${CENTRAL_RESOURCE_PREFIX:-${COMPOSE_PROJECT_NAME:-nexolab-central}}"
    assert central["networks"]["central"]["name"] == central_prefix
    assert {
        value["name"] for value in central["volumes"].values()
    } == {
        f"{central_prefix}-mqtt-data",
        f"{central_prefix}-postgres-data",
        f"{central_prefix}-object-storage-data",
        f"{central_prefix}-telemetry-ingestion-data",
    }

    observability_prefix = (
        "${OBSERVABILITY_RESOURCE_PREFIX:-${COMPOSE_PROJECT_NAME:-nexolab-observability}}"
    )
    assert {
        value["name"] for value in observability["volumes"].values()
    } == {
        f"{observability_prefix}-prometheus-data",
        f"{observability_prefix}-alertmanager-data",
        f"{observability_prefix}-grafana-data",
        f"{observability_prefix}-alert-events",
    }


def test_grafana_plugin_preinstallation_is_disabled() -> None:
    source = ROOT / "infrastructure/compose/compose.observability.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    environment = payload["services"]["grafana"]["environment"]

    assert environment["GF_PLUGINS_PLUGIN_ADMIN_ENABLED"] == "false"
    assert environment["GF_PLUGINS_PREINSTALL_DISABLED"] == "true"
    assert environment["GF_PLUGINS_PREINSTALL_AUTO_UPDATE"] == "false"


def test_rules_reject_missing_required_alert(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/prometheus/rules/nexolab-platform.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    alert_group = next(
        group
        for group in payload["groups"]
        if group["name"] == "nexolab-platform-alerts"
    )
    alert_group["rules"] = [
        rule
        for rule in alert_group["rules"]
        if rule.get("alert") != "NexolabTelemetryServiceDown"
    ]
    path = tmp_path / "rules.yml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="alert rules are missing"):
        validator.validate_rules(path)


def test_disaster_recovery_liveness_and_metric_contract_are_actionable() -> None:
    rules = alert_rules()
    exporter = rules["NexolabDisasterRecoveryExporterDown"]
    contract = rules["NexolabDisasterRecoveryMetricsMissing"]

    assert exporter["expr"] == 'up{job="disaster-recovery-status"} == 0'
    assert exporter["labels"]["severity"] == "critical"
    assert exporter["annotations"]["runbook_url"] == "/docs/operations/disaster-recovery.md"

    expression = contract["expr"]
    assert 'up{job="disaster-recovery-status"} == 1' in expression
    for metric in (
        "nexolab_dr_last_verified_backup_timestamp_seconds",
        "nexolab_dr_last_bundle_verification_success",
        "nexolab_dr_backup_destination_free_bytes",
        "nexolab_dr_backup_destination_capacity_bytes",
    ):
        assert f"absent({metric})" in expression
    assert contract["labels"]["severity"] == "critical"
    assert contract["annotations"]["runbook_url"] == "/docs/operations/disaster-recovery.md"


def test_alertmanager_requires_resolved_delivery(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/alertmanager/alertmanager.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["receivers"][0]["webhook_configs"][0]["send_resolved"] = False
    path = tmp_path / "alertmanager.yml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="resolved alert delivery"):
        validator.validate_alertmanager(path)


def test_alertmanager_inhibition_is_limited_to_explicit_pairs() -> None:
    source = ROOT / "infrastructure/observability/alertmanager/alertmanager.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    pairs = {
        (
            matcher_value(rule["source_matchers"][0], "alertname"),
            matcher_value(rule["target_matchers"][0], "alertname"),
        )
        for rule in payload["inhibit_rules"]
    }
    assert pairs == {
        ("NexolabIngestionQueuePressureCritical", "NexolabIngestionQueuePressureWarning"),
        (
            "NexolabIngestionSpoolUtilizationCritical",
            "NexolabIngestionSpoolUtilizationWarning",
        ),
        ("NexolabIngestionLagCritical", "NexolabIngestionLagWarning"),
        ("NexolabPersistenceFailuresSustained", "NexolabPersistenceFailures"),
        ("NexolabDeadLetterBurst", "NexolabDeadLetterGrowth"),
        ("NexolabVerifiedBackupStaleCritical", "NexolabVerifiedBackupStaleWarning"),
    }
    assert all(rule["equal"] == ["service"] for rule in payload["inhibit_rules"])
    assert all(
        not any("severity=" in matcher for matcher in rule["source_matchers"] + rule["target_matchers"])
        for rule in payload["inhibit_rules"]
    )

    unrelated_warning = "NexolabWebSocketSlowConsumers"
    queue_critical = "NexolabIngestionQueuePressureCritical"
    assert not any(
        matcher_value(rule["source_matchers"][0], "alertname") == queue_critical
        and matcher_value(rule["target_matchers"][0], "alertname") == unrelated_warning
        for rule in payload["inhibit_rules"]
    )


def test_dashboard_rejects_duplicate_panel_ids(tmp_path: Path) -> None:
    source = (
        ROOT
        / "infrastructure/observability/grafana/dashboards/nexolab-platform-overview.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["panels"][1]["id"] = payload["panels"][0]["id"]
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.PolicyError, match="panel IDs must be unique"):
        validator.validate_dashboard(path)


def test_dashboard_rejects_missing_recovery_query(tmp_path: Path) -> None:
    source = (
        ROOT
        / "infrastructure/observability/grafana/dashboards/nexolab-platform-overview.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    for panel in payload["panels"]:
        for target in panel.get("targets", []):
            if target.get("expr") == "nexolab:verified_backup_age_seconds":
                target["expr"] = "vector(0)"
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.PolicyError, match="dashboard queries are missing"):
        validator.validate_dashboard(path)


def test_durable_ingestion_spool_alert_contract_is_actionable() -> None:
    source = (
        ROOT
        / "infrastructure/observability/prometheus/rules/nexolab-ingestion-spool.yml"
    )
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    groups = {group["name"]: group for group in payload["groups"]}
    recording = {
        rule["record"]: rule
        for rule in groups["nexolab-ingestion-spool-recording"]["rules"]
    }
    alerts = {
        rule["alert"]: rule
        for rule in groups["nexolab-ingestion-spool-alerts"]["rules"]
    }

    assert set(recording) == {
        "nexolab:ingestion_spool_record_utilization_ratio",
        "nexolab:ingestion_spool_byte_utilization_ratio",
        "nexolab:ingestion_spool_utilization_ratio",
    }
    assert set(alerts) == {
        "NexolabIngestionSpoolUnavailable",
        "NexolabIngestionSpoolUtilizationWarning",
        "NexolabIngestionSpoolUtilizationCritical",
        "NexolabIngestionSpoolBacklogAged",
        "NexolabIngestionSpoolTerminalRecords",
        "NexolabIngestionSpoolCapacityFailures",
        "NexolabIngestionSpoolErrors",
        "NexolabMqttManualAckFailures",
    }
    for alert in alerts.values():
        assert alert["labels"]["service"] == "telemetry-service"
        assert alert["labels"]["severity"] in {"warning", "critical"}
        assert alert["annotations"]["runbook_url"].startswith(
            "/docs/operations/telemetry-backend-runbook.md#"
        )

    assert alerts["NexolabIngestionSpoolUnavailable"]["expr"] == (
        "nexolab_telemetry_spool_ready == 0"
    )
    assert alerts["NexolabIngestionSpoolTerminalRecords"]["expr"] == (
        "nexolab_telemetry_spool_terminal_records > 0"
    )
    assert "spool_capacity_failure_total" in alerts[
        "NexolabIngestionSpoolCapacityFailures"
    ]["expr"]
    assert "mqtt_ack_failure_total" in alerts[
        "NexolabMqttManualAckFailures"
    ]["expr"]
