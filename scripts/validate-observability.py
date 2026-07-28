#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

REQUIRED_IMAGES = {
    "prometheus": "prom/prometheus:v3.13.0",
    "alertmanager": "prom/alertmanager:v0.32.1",
    "grafana": "grafana/grafana:13.1.0",
}
REQUIRED_JOBS = {
    "prometheus",
    "telemetry-service",
    "alertmanager",
    "observability-alert-sink",
    "disaster-recovery-status",
}
REQUIRED_RECORDS = {
    "nexolab:telemetry_service:availability_ratio_30d",
    "nexolab:platform_dependency_ready",
    "nexolab:ingestion_queue_utilization_ratio",
    "nexolab:ingestion_received_per_second",
    "nexolab:ingestion_persisted_per_second",
    "nexolab:ingestion_rejected_per_second",
    "nexolab:ingestion_duplicate_per_second",
    "nexolab:persistence_freshness_age_seconds",
    "nexolab:verified_backup_age_seconds",
    "nexolab:offsite_backup_copy_age_seconds",
    "nexolab:restore_rehearsal_age_seconds",
    "nexolab:backup_destination_utilization_ratio",
}
REQUIRED_ALERTS = {
    "NexolabTelemetryServiceDown",
    "NexolabTelemetryMqttDisconnected",
    "NexolabTelemetryDatabaseUnavailable",
    "NexolabIngestionQueuePressureWarning",
    "NexolabIngestionQueuePressureCritical",
    "NexolabIngestionQueueDroppedWork",
    "NexolabIngestionLagWarning",
    "NexolabIngestionLagCritical",
    "NexolabPersistenceFailures",
    "NexolabPersistenceFailuresSustained",
    "NexolabDeadLetterGrowth",
    "NexolabDeadLetterBurst",
    "NexolabNoRecentPersistenceWhileReceiving",
    "NexolabWebSocketSlowConsumers",
    "NexolabWebSocketSendTimeouts",
    "NexolabVerifiedBackupStaleWarning",
    "NexolabVerifiedBackupStaleCritical",
    "NexolabBackupVerificationFailed",
    "NexolabOffsiteBackupCopyStale",
    "NexolabRestoreRehearsalStale",
    "NexolabBackupDestinationCapacityCritical",
    "NexolabAlertDeliverySinkDown",
}
REQUIRED_DASHBOARD_QUERIES = {
    'up{job="telemetry-service"}',
    "nexolab:platform_dependency_ready",
    "nexolab_telemetry_mqtt_connected",
    "nexolab_telemetry_database_ready",
    "nexolab:ingestion_queue_utilization_ratio * 100",
    "nexolab_telemetry_ingestion_lag_seconds",
    "nexolab:ingestion_received_per_second",
    "nexolab:ingestion_persisted_per_second",
    "nexolab:verified_backup_age_seconds",
    "nexolab_dr_last_bundle_verification_success",
    'count(ALERTS{alertstate="firing"})',
    "nexolab_alert_sink_resolved_total",
}
SECRET_PATTERN = re.compile(
    "BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY|"
    + "g"
    + r"hp_[A-Za-z0-9]{20,}|"
    + "s"
    + r"k-[A-Za-z0-9]{20,}|"
    + r"(?im)^\s*(?:password|token|secret|api[_-]?key)\s*[:=]\s*[^$<{\s][^\s]*"
)


class PolicyError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise PolicyError(message)


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain a YAML object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"{path} must contain a JSON object")
    return value


def validate_compose(path: Path) -> None:
    services = load_yaml(path).get("services")
    require(isinstance(services, dict), "observability Compose must define services")
    for service, expected_image in REQUIRED_IMAGES.items():
        definition = services.get(service)
        require(isinstance(definition, dict), f"Compose service {service!r} is required")
        require(
            definition.get("image") == expected_image,
            f"Compose service {service!r} must pin {expected_image}",
        )
        for port in definition.get("ports", []):
            require(
                isinstance(port, str)
                and port.startswith("${OBSERVABILITY_BIND_ADDRESS:-127.0.0.1}:"),
                f"{service} ports must bind to configurable loopback by default",
            )

    grafana = services["grafana"].get("environment")
    require(isinstance(grafana, dict), "Grafana environment must be a mapping")
    require(grafana.get("GF_AUTH_ANONYMOUS_ENABLED") == "false", "anonymous access must be disabled")
    require(grafana.get("GF_USERS_ALLOW_SIGN_UP") == "false", "Grafana signup must be disabled")
    require(
        str(grafana.get("GF_SECURITY_ADMIN_PASSWORD", "")).startswith("${"),
        "Grafana admin password must be externally provided",
    )
    require(
        grafana.get("GF_PLUGINS_PLUGIN_ADMIN_ENABLED") == "false",
        "Grafana runtime plugin administration must be disabled",
    )
    for service, definition in services.items():
        if isinstance(definition, dict) and isinstance(definition.get("image"), str):
            require(not definition["image"].endswith(":latest"), f"{service} must not use latest")


def validate_prometheus(path: Path) -> None:
    config = load_yaml(path)
    global_config = config.get("global")
    require(isinstance(global_config, dict), "Prometheus global config is required")
    require(global_config.get("scrape_interval") == "5s", "scrape_interval must be 5s")
    require(global_config.get("evaluation_interval") == "5s", "evaluation_interval must be 5s")
    scrape_configs = config.get("scrape_configs")
    require(isinstance(scrape_configs, list), "scrape_configs must be a list")
    jobs = {item.get("job_name") for item in scrape_configs if isinstance(item, dict)}
    require(REQUIRED_JOBS <= jobs, f"Prometheus jobs missing: {sorted(REQUIRED_JOBS - jobs)}")
    require("alertmanager:9093" in json.dumps(config.get("alerting")), "Alertmanager target is required")
    require(
        "/etc/prometheus/rules/*.yml" in config.get("rule_files", []),
        "versioned Prometheus rules are required",
    )


def validate_rules(path: Path) -> None:
    groups = load_yaml(path).get("groups")
    require(isinstance(groups, list) and groups, "Prometheus rule groups are required")
    records: set[str] = set()
    alerts: set[str] = set()
    for group in groups:
        require(isinstance(group, dict), "rule group must be an object")
        rules = group.get("rules")
        require(isinstance(rules, list), "rule group rules must be a list")
        for rule in rules:
            require(isinstance(rule, dict), "rule must be an object")
            require(isinstance(rule.get("expr"), str) and rule["expr"].strip(), "rule expr is required")
            record = rule.get("record")
            alert = rule.get("alert")
            require(bool(record) != bool(alert), "rule must define exactly one record or alert")
            if isinstance(record, str):
                require(record not in records, f"duplicate recording rule: {record}")
                records.add(record)
                continue
            require(isinstance(alert, str) and alert not in alerts, f"invalid or duplicate alert: {alert}")
            alerts.add(alert)
            labels = rule.get("labels")
            annotations = rule.get("annotations")
            require(isinstance(labels, dict), f"{alert} labels are required")
            require(labels.get("severity") in {"warning", "critical"}, f"{alert} severity is invalid")
            require(isinstance(annotations, dict), f"{alert} annotations are required")
            require(bool(annotations.get("summary")), f"{alert} summary is required")
            require(bool(annotations.get("description")), f"{alert} description is required")
            if labels.get("severity") == "critical" and labels.get("service") in {
                "telemetry-service",
                "disaster-recovery",
            }:
                require(bool(annotations.get("runbook_url")), f"{alert} must reference a runbook")
    require(REQUIRED_RECORDS <= records, f"recording rules are missing: {sorted(REQUIRED_RECORDS - records)}")
    require(REQUIRED_ALERTS <= alerts, f"alert rules are missing: {sorted(REQUIRED_ALERTS - alerts)}")


def validate_alertmanager(path: Path) -> None:
    config = load_yaml(path)
    route = config.get("route")
    require(isinstance(route, dict), "Alertmanager route is required")
    require(route.get("receiver") == "nexolab-local-audit", "default receiver must be local audit")
    require(
        set(route.get("group_by", [])) >= {"alertname", "service", "severity"},
        "Alertmanager grouping is incomplete",
    )
    receivers = config.get("receivers")
    require(isinstance(receivers, list), "Alertmanager receivers are required")
    receiver = next(
        (item for item in receivers if isinstance(item, dict) and item.get("name") == "nexolab-local-audit"),
        None,
    )
    require(isinstance(receiver, dict), "local audit receiver is required")
    webhooks = receiver.get("webhook_configs")
    require(isinstance(webhooks, list) and len(webhooks) == 1, "exactly one local webhook is required")
    webhook = webhooks[0]
    require(webhook.get("url") == "http://observability-alert-sink:8080/alerts", "webhook target is invalid")
    require(webhook.get("send_resolved") is True, "resolved alert delivery is required")
    require(bool(config.get("inhibit_rules")), "critical-to-warning inhibition is required")


def iter_panels(panels: Iterable[Any]):
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        yield panel
        nested = panel.get("panels")
        if isinstance(nested, list):
            yield from iter_panels(nested)


def validate_dashboard(path: Path) -> None:
    dashboard = load_json(path)
    require(dashboard.get("uid") == "nexolab-platform-overview", "dashboard UID must be deterministic")
    require(dashboard.get("editable") is False, "dashboard must not be UI-editable")
    require(dashboard.get("refresh") == "5s", "dashboard refresh must be 5s")
    panels = list(iter_panels(dashboard.get("panels", [])))
    ids = [panel.get("id") for panel in panels]
    require(all(isinstance(value, int) and value > 0 for value in ids), "panel IDs must be positive")
    require(len(ids) == len(set(ids)), "Grafana panel IDs must be unique")
    require(len(ids) >= 20, "operator dashboard must contain at least twenty panels/rows")
    expressions: set[str] = set()
    for panel in panels:
        if panel.get("type") == "row":
            continue
        datasource = panel.get("datasource")
        require(
            isinstance(datasource, dict) and datasource.get("uid") == "nexolab-prometheus",
            f"panel {panel.get('id')} must use provisioned Prometheus",
        )
        for target in panel.get("targets", []):
            if isinstance(target, dict) and isinstance(target.get("expr"), str):
                expressions.add(target["expr"])
    require(
        REQUIRED_DASHBOARD_QUERIES <= expressions,
        f"Grafana dashboard queries are missing: {sorted(REQUIRED_DASHBOARD_QUERIES - expressions)}",
    )


def validate_secrets(paths: Iterable[Path]) -> None:
    for path in paths:
        match = SECRET_PATTERN.search(path.read_text(encoding="utf-8"))
        require(match is None, f"secret-like versioned material found in {path}: {match.group(0)!r}")


def validate_repository(root: Path) -> None:
    files = {
        "compose": root / "infrastructure/compose/compose.observability.yaml",
        "prometheus": root / "infrastructure/observability/prometheus/prometheus.yml",
        "rules": root / "infrastructure/observability/prometheus/rules/nexolab-platform.yml",
        "alertmanager": root / "infrastructure/observability/alertmanager/alertmanager.yml",
        "datasource": root / "infrastructure/observability/grafana/provisioning/datasources/prometheus.yml",
        "provider": root / "infrastructure/observability/grafana/provisioning/dashboards/nexolab.yml",
        "dashboard": root / "infrastructure/observability/grafana/dashboards/nexolab-platform-overview.json",
        "alert_sink": root / "scripts/observability-alert-sink.py",
        "textfile": root / "scripts/serve-prometheus-textfile.py",
    }
    missing = [str(path.relative_to(root)) for path in files.values() if not path.is_file()]
    require(not missing, f"observability files are missing: {missing}")
    validate_compose(files["compose"])
    validate_prometheus(files["prometheus"])
    validate_rules(files["rules"])
    validate_alertmanager(files["alertmanager"])
    validate_dashboard(files["dashboard"])
    validate_secrets(files.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate NEXOLAB observability policy")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        validate_repository(args.repository_root.resolve())
    except (OSError, json.JSONDecodeError, yaml.YAMLError, PolicyError) as error:
        print(f"observability policy validation failed: {error}", file=sys.stderr)
        return 1
    print("observability policy validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
