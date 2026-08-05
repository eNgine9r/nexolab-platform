from __future__ import annotations

import importlib.util
from pathlib import Path

from app.security.authorization import Permission, Role, permissions_for_role


ROOT = Path(__file__).resolve().parents[3]


def test_migration_extends_the_single_current_head_and_is_reversible() -> None:
    path = (
        ROOT
        / "services/telemetry-service/migrations/versions"
        / "20260805_0022_add_live_dashboards.py"
    )
    spec = importlib.util.spec_from_file_location("live_dashboard_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.revision == "20260805_0022"
    assert module.down_revision == "20260801_0021"
    source = path.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "live_dashboards"' in source
    assert 'op.create_table(\n        "live_dashboard_items"' in source
    assert 'op.drop_table("live_dashboard_items")' in source
    assert 'op.drop_table("live_dashboards")' in source


def test_dashboard_configuration_has_no_acquisition_dependencies() -> None:
    paths = (
        ROOT / "services/telemetry-service/app/live_dashboard/models.py",
        ROOT / "services/telemetry-service/app/live_dashboard/schemas.py",
        ROOT / "services/telemetry-service/app/live_dashboard/repository.py",
        ROOT / "services/telemetry-service/app/live_dashboard/api.py",
    )
    forbidden = (
        "adaptive_scheduler",
        "acquisition_registry",
        "modbus_rtu",
        "read_channel(",
        "read_metric(",
        "priority_for(",
        "eligible_targets(",
        "/api/v1/acquisition",
        "sample_interval_seconds",
    )
    offenders = {
        str(path.relative_to(ROOT)): token
        for path in paths
        for token in forbidden
        if token in path.read_text(encoding="utf-8").casefold()
    }
    assert offenders == {}


def test_refresh_and_time_window_are_persisted_display_preferences_only() -> None:
    repository = (
        ROOT / "services/telemetry-service/app/live_dashboard/repository.py"
    ).read_text(encoding="utf-8")
    models = (
        ROOT / "services/telemetry-service/app/live_dashboard/models.py"
    ).read_text(encoding="utf-8")

    assert "refresh_seconds" in repository
    assert "time_window" in repository
    assert "refresh_seconds" in models
    assert "time_window" in models
    assert "device_agent" not in repository.casefold()
    assert "scheduler" not in repository.casefold()
    assert "registry" not in repository.casefold()


def test_live_dashboard_write_permission_is_explicit_and_readers_remain_read_only() -> None:
    assert Permission.MANAGE_LIVE_DASHBOARDS in permissions_for_role(
        Role.OPERATOR
    )
    assert Permission.MANAGE_LIVE_DASHBOARDS in permissions_for_role(
        Role.ENGINEER
    )
    assert Permission.MANAGE_LIVE_DASHBOARDS in permissions_for_role(
        Role.LABORATORY_MANAGER
    )
    assert Permission.MANAGE_LIVE_DASHBOARDS not in permissions_for_role(
        Role.VIEWER
    )
    assert Permission.MANAGE_LIVE_DASHBOARDS not in permissions_for_role(
        Role.AUDITOR
    )
