from __future__ import annotations

import base64
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.nodes.broker_adapter import BrokerControlAdapterError
from app.nodes.broker_control import BrokerControlCryptoError


def test_broker_control_remains_disabled_by_default() -> None:
    settings = Settings(mqtt_enabled=False)
    assert settings.broker_control_enabled is False


def test_enabled_broker_control_requires_all_secret_boundaries() -> None:
    with pytest.raises(ValidationError, match="required settings are missing"):
        Settings(
            mqtt_enabled=False,
            broker_control_enabled=True,
        )


def test_broker_control_retry_and_lock_bounds_are_validated() -> None:
    with pytest.raises(ValidationError, match="RETRY_MAX_SECONDS"):
        Settings(
            broker_control_retry_initial_seconds=10,
            broker_control_retry_max_seconds=5,
        )

    with pytest.raises(ValidationError, match="STALE_LOCK_SECONDS"):
        Settings(
            broker_control_command_timeout_seconds=30,
            broker_control_stale_lock_seconds=30,
        )


def write_bootstrap_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    key_file = tmp_path / "broker-control-key"
    key_file.write_text(
        base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
        encoding="ascii",
    )
    key_file.chmod(0o600)

    password_file = tmp_path / "admin-password"
    password_file.write_text("nxl_mqtt_admin_test_secret", encoding="utf-8")
    password_file.chmod(0o600)

    executable = tmp_path / "nexolab-dynsec-admin"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    return key_file, password_file, executable


def enabled_settings(tmp_path: Path, **overrides) -> Settings:
    key_file, password_file, executable = write_bootstrap_files(tmp_path)
    values = {
        "mqtt_enabled": False,
        "database_url": f"sqlite:///{tmp_path / 'bootstrap.db'}",
        "broker_control_enabled": True,
        "broker_control_encryption_key_file": str(key_file),
        "broker_control_encryption_key_id": "broker-key-v1",
        "broker_control_admin_executable": str(executable),
        "broker_control_admin_username": "nexolab-security-admin",
        "broker_control_admin_client_id": "nexolab-broker-control-worker",
        "broker_control_admin_password_file": str(password_file),
    }
    values.update(overrides)
    return Settings(**values)


def test_create_app_bootstraps_repository_and_worker_from_mounted_files(
    tmp_path: Path,
) -> None:
    app = create_app(enabled_settings(tmp_path))

    assert app.state.broker_control_repository is not None
    assert app.state.broker_control_worker is not None
    app.state.database.dispose()


def test_corrupted_encryption_key_fails_closed(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    Path(settings.broker_control_encryption_key_file or "").write_text(
        "not-base64url",
        encoding="ascii",
    )

    with pytest.raises(BrokerControlCryptoError, match="not valid base64url"):
        create_app(settings)


def test_missing_admin_executable_fails_closed(tmp_path: Path) -> None:
    settings = enabled_settings(
        tmp_path,
        broker_control_admin_executable=str(tmp_path / "missing-admin"),
    )

    with pytest.raises(BrokerControlAdapterError, match="not available"):
        create_app(settings)
