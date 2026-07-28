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


def test_rules_reject_missing_required_alert(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/prometheus/rules/nexolab-platform.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    alert_group = next(group for group in payload["groups"] if group["name"] == "nexolab-platform-alerts")
    alert_group["rules"] = [
        rule for rule in alert_group["rules"] if rule.get("alert") != "NexolabTelemetryServiceDown"
    ]
    path = tmp_path / "rules.yml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="alert rules are missing"):
        validator.validate_rules(path)


def test_alertmanager_requires_resolved_delivery(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/alertmanager/alertmanager.yml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["receivers"][0]["webhook_configs"][0]["send_resolved"] = False
    path = tmp_path / "alertmanager.yml"
    write_yaml(path, payload)

    with pytest.raises(validator.PolicyError, match="resolved alert delivery"):
        validator.validate_alertmanager(path)


def test_dashboard_rejects_duplicate_panel_ids(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/grafana/dashboards/nexolab-platform-overview.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["panels"][1]["id"] = payload["panels"][0]["id"]
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.PolicyError, match="panel IDs must be unique"):
        validator.validate_dashboard(path)


def test_dashboard_rejects_missing_recovery_query(tmp_path: Path) -> None:
    source = ROOT / "infrastructure/observability/grafana/dashboards/nexolab-platform-overview.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    for panel in payload["panels"]:
        for target in panel.get("targets", []):
            if target.get("expr") == "nexolab:verified_backup_age_seconds":
                target["expr"] = "vector(0)"
    path = tmp_path / "dashboard.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(validator.PolicyError, match="dashboard queries are missing"):
        validator.validate_dashboard(path)
