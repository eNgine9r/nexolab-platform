from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.mqtt_tls import MQTTTLSConfig
from app.nodes.broker_adapter import DynamicSecurityAdminAdapter


def write_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_adapter_exports_only_tls_paths(tmp_path: Path) -> None:
    executable = write_file(tmp_path / "admin", "#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    admin_password = write_file(tmp_path / "admin-password", "secret")
    ca_file = write_file(tmp_path / "ca.pem", "ca")
    certificate_file = write_file(tmp_path / "client.pem", "certificate")
    key_file = write_file(tmp_path / "client.key", "private-key")

    adapter = DynamicSecurityAdminAdapter(
        executable=str(executable),
        broker_host="mqtt.nexolab.internal",
        broker_port=8883,
        admin_username="admin",
        admin_client_id="broker-control",
        admin_password_file=str(admin_password),
        timeout_seconds=2,
        tls_config=MQTTTLSConfig(
            enabled=True,
            ca_file=ca_file,
            client_certificate_file=certificate_file,
            client_key_file=key_file,
        ),
    )

    assert adapter._environment["NEXOLAB_MQTT_TLS_REQUIRED"] == "true"
    assert adapter._environment["NEXOLAB_MQTT_TLS_CA_FILE"] == str(ca_file)
    assert adapter._environment["NEXOLAB_MQTT_TLS_CERT_FILE"] == str(
        certificate_file
    )
    assert adapter._environment["NEXOLAB_MQTT_TLS_KEY_FILE"] == str(key_file)
    assert "private-key" not in repr(adapter._environment)
    assert "--insecure" not in repr(adapter._environment)


def test_adapter_disables_tls_without_exporting_material(tmp_path: Path) -> None:
    executable = write_file(tmp_path / "admin", "#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    admin_password = write_file(tmp_path / "admin-password", "secret")

    adapter = DynamicSecurityAdminAdapter(
        executable=str(executable),
        broker_host="mqtt",
        broker_port=1883,
        admin_username="admin",
        admin_client_id="broker-control",
        admin_password_file=str(admin_password),
        timeout_seconds=2,
    )

    assert adapter._environment["NEXOLAB_MQTT_TLS_REQUIRED"] == "false"
    assert "NEXOLAB_MQTT_TLS_CA_FILE" not in adapter._environment


def run_admin_script(
    tmp_path: Path,
    *,
    tls_required: str,
    ca_file: str = "",
    certificate_file: str = "",
    key_file: str = "",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure/mqtt/dynamic-security/dynsec-admin.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    captured = tmp_path / "captured-options"
    fake_ctrl = fake_bin / "mosquitto_ctrl"
    fake_ctrl.write_text(
        "#!/bin/sh\n"
        "test \"$1\" = -o\n"
        "cp \"$2\" \"$CAPTURED_OPTIONS\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ctrl.chmod(0o700)
    password = write_file(tmp_path / "admin-password", "admin-secret")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "CAPTURED_OPTIONS": str(captured),
            "NEXOLAB_MQTT_ADMIN_PASSWORD_FILE": str(password),
            "NEXOLAB_MQTT_TLS_REQUIRED": tls_required,
            "NEXOLAB_MQTT_TLS_CA_FILE": ca_file,
            "NEXOLAB_MQTT_TLS_CERT_FILE": certificate_file,
            "NEXOLAB_MQTT_TLS_KEY_FILE": key_file,
        }
    )
    result = subprocess.run(
        [str(script), "list-clients"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return result, captured


def test_admin_script_builds_verified_tls_options(tmp_path: Path) -> None:
    ca_file = write_file(tmp_path / "ca.pem", "ca")
    certificate_file = write_file(tmp_path / "client.pem", "certificate")
    key_file = write_file(tmp_path / "client.key", "private-key")

    result, captured = run_admin_script(
        tmp_path,
        tls_required="true",
        ca_file=str(ca_file),
        certificate_file=str(certificate_file),
        key_file=str(key_file),
    )

    assert result.returncode == 0, result.stderr
    options = captured.read_text(encoding="utf-8")
    assert f"--cafile {ca_file}" in options
    assert "--tls-version tlsv1.2" in options
    assert f"--cert {certificate_file}" in options
    assert f"--key {key_file}" in options
    assert "--insecure" not in options
    assert "private-key" not in options


def test_admin_script_fails_closed_for_partial_tls(tmp_path: Path) -> None:
    ca_file = write_file(tmp_path / "ca.pem", "ca")
    certificate_file = write_file(tmp_path / "client.pem", "certificate")

    disabled, _ = run_admin_script(
        tmp_path / "disabled",
        tls_required="false",
        ca_file=str(ca_file),
    )
    missing_key, _ = run_admin_script(
        tmp_path / "partial",
        tls_required="true",
        ca_file=str(ca_file),
        certificate_file=str(certificate_file),
    )

    assert disabled.returncode == 72
    assert missing_key.returncode == 74


def test_admin_script_copies_are_identical_and_have_no_bypass() -> None:
    root = Path(__file__).resolve().parents[3]
    infrastructure_script = (
        root / "infrastructure/mqtt/dynamic-security/dynsec-admin.sh"
    )
    service_script = (
        root / "services/telemetry-service/bin/nexolab-dynsec-admin"
    )
    assert infrastructure_script.read_bytes() == service_script.read_bytes()
    source = infrastructure_script.read_text(encoding="utf-8")
    assert "--insecure" not in source


def test_application_passes_verified_tls_to_broker_adapter() -> None:
    root = Path(__file__).resolve().parents[3]
    source = (root / "services/telemetry-service/app/main.py").read_text(
        encoding="utf-8"
    )
    assert "from app.mqtt_tls import MQTTTLSConfig" in source
    assert "tls_config=MQTTTLSConfig.from_settings(settings)" in source


def run_admin_with_diagnostic(
    tmp_path: Path,
    diagnostic: str,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    script = root / "infrastructure/mqtt/dynamic-security/dynsec-admin.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ctrl = fake_bin / "mosquitto_ctrl"
    fake_ctrl.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$CTRL_DIAGNOSTIC\" >&2\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_ctrl.chmod(0o700)
    password = write_file(tmp_path / "admin-password", "admin-secret")
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "CTRL_DIAGNOSTIC": diagnostic,
            "NEXOLAB_MQTT_ADMIN_PASSWORD_FILE": str(password),
        }
    )
    return subprocess.run(
        [str(script), "list-clients"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_admin_script_allows_non_error_cli_warning(tmp_path: Path) -> None:
    result = run_admin_with_diagnostic(
        tmp_path,
        "Warning: client session closed cleanly.",
    )

    assert result.returncode == 0
    assert "Warning" in result.stderr


def test_admin_script_rejects_tls_diagnostic_even_on_zero_exit(
    tmp_path: Path,
) -> None:
    result = run_admin_with_diagnostic(
        tmp_path,
        "Error: A TLS certificate verification failure occurred.",
    )

    assert result.returncode == 77
    assert "TLS certificate verification" in result.stderr
