from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_compose_resources_are_project_scoped() -> None:
    central = load_yaml(ROOT / "infrastructure/compose/compose.central.yaml")
    observability = load_yaml(
        ROOT / "infrastructure/compose/compose.observability.yaml"
    )

    for volume in central["volumes"].values():
        assert str(volume["name"]).startswith("${COMPOSE_PROJECT_NAME:-")
    assert str(central["networks"]["central"]["name"]).startswith(
        "${COMPOSE_PROJECT_NAME:-"
    )
    for volume in observability["volumes"].values():
        assert str(volume["name"]).startswith("${COMPOSE_PROJECT_NAME:-")


def test_inhibition_is_limited_to_explicit_alert_pairs() -> None:
    config = load_yaml(
        ROOT
        / "infrastructure/observability/alertmanager/alertmanager.yml"
    )
    rules = config["inhibit_rules"]
    assert isinstance(rules, list)
    assert len(rules) == 4

    pairs = {
        (
            rule["source_matchers"][0],
            rule["target_matchers"][0],
        )
        for rule in rules
    }
    assert pairs == {
        (
            'alertname="NexolabIngestionQueuePressureCritical"',
            'alertname="NexolabIngestionQueuePressureWarning"',
        ),
        (
            'alertname="NexolabIngestionLagCritical"',
            'alertname="NexolabIngestionLagWarning"',
        ),
        (
            'alertname="NexolabPersistenceFailuresSustained"',
            'alertname="NexolabPersistenceFailures"',
        ),
        (
            'alertname="NexolabVerifiedBackupStaleCritical"',
            'alertname="NexolabVerifiedBackupStaleWarning"',
        ),
    }
    assert all(rule["equal"] == ["service"] for rule in rules)


def test_disaster_recovery_absence_alerts_are_versioned() -> None:
    rules = load_yaml(
        ROOT
        / "infrastructure/observability/prometheus/rules/nexolab-observability-hardening.yml"
    )["groups"][0]["rules"]
    alerts = {rule["alert"]: rule for rule in rules}

    exporter = alerts["NexolabDisasterRecoveryExporterDown"]
    assert 'absent(up{job="disaster-recovery-status"})' in exporter["expr"]
    assert exporter["labels"]["severity"] == "critical"
    assert exporter["annotations"]["runbook_url"]

    metrics = alerts["NexolabDisasterRecoveryMetricsMissing"]
    expression = metrics["expr"]
    for name in (
        "nexolab_dr_last_verified_backup_timestamp_seconds",
        "nexolab_dr_last_offsite_copy_timestamp_seconds",
        "nexolab_dr_last_restore_rehearsal_timestamp_seconds",
        "nexolab_dr_last_bundle_verification_success",
    ):
        assert f"absent({name})" in expression
    assert metrics["labels"]["severity"] == "critical"
    assert metrics["annotations"]["runbook_url"]
