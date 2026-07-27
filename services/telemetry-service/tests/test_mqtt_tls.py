from __future__ import annotations

import ssl
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.config import Settings
from app.mqtt_tls import MQTTTLSConfig


def write_material(path: Path) -> Path:
    path.write_text("test-material", encoding="utf-8")
    path.chmod(0o600)
    return path


def test_disabled_tls_has_no_material() -> None:
    config = MQTTTLSConfig.from_settings(Settings(mqtt_enabled=False))

    assert config.enabled is False
    assert config.ca_file is None


def test_disabled_tls_rejects_configured_files(tmp_path: Path) -> None:
    ca_file = write_material(tmp_path / "ca.pem")
    settings = Settings(
        mqtt_enabled=False,
        mqtt_tls_ca_file=str(ca_file),
    )

    with pytest.raises(RuntimeError, match="MQTT_TLS_REQUIRED"):
        MQTTTLSConfig.from_settings(settings)


def test_enabled_tls_requires_readable_ca(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="MQTT_TLS_CA_FILE"):
        MQTTTLSConfig.from_settings(
            Settings(mqtt_enabled=False, mqtt_tls_required=True)
        )

    with pytest.raises(RuntimeError, match="not readable"):
        MQTTTLSConfig.from_settings(
            Settings(
                mqtt_enabled=False,
                mqtt_tls_required=True,
                mqtt_tls_ca_file=str(tmp_path / "missing-ca.pem"),
            )
        )


def test_client_certificate_and_key_are_atomic(tmp_path: Path) -> None:
    ca_file = write_material(tmp_path / "ca.pem")
    certificate_file = write_material(tmp_path / "client.pem")
    key_file = write_material(tmp_path / "client.key")

    for field, value in (
        ("mqtt_tls_cert_file", str(certificate_file)),
        ("mqtt_tls_key_file", str(key_file)),
    ):
        settings = Settings(
            mqtt_enabled=False,
            mqtt_tls_required=True,
            mqtt_tls_ca_file=str(ca_file),
            **{field: value},
        )
        with pytest.raises(RuntimeError, match="configured together"):
            MQTTTLSConfig.from_settings(settings)


@patch("app.mqtt_tls.ssl.create_default_context")
def test_context_requires_ca_hostname_and_tls12_or_newer(
    create_default_context: Mock,
    tmp_path: Path,
) -> None:
    ca_file = write_material(tmp_path / "ca.pem")
    certificate_file = write_material(tmp_path / "client.pem")
    key_file = write_material(tmp_path / "client.key")
    settings = Settings(
        mqtt_enabled=False,
        mqtt_tls_required=True,
        mqtt_tls_ca_file=str(ca_file),
        mqtt_tls_cert_file=str(certificate_file),
        mqtt_tls_key_file=str(key_file),
    )
    context = create_default_context.return_value
    client = Mock()

    config = MQTTTLSConfig.from_settings(settings)
    config.apply(client)

    create_default_context.assert_called_once_with(
        purpose=ssl.Purpose.SERVER_AUTH,
        cafile=str(ca_file),
    )
    assert context.minimum_version is ssl.TLSVersion.TLSv1_2
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True
    context.load_cert_chain.assert_called_once_with(
        certfile=str(certificate_file),
        keyfile=str(key_file),
    )
    client.tls_set_context.assert_called_once_with(context)


def test_source_contains_no_verification_bypass() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "mqtt_tls.py"
    ).read_text(encoding="utf-8")

    assert "tls_insecure_set" not in source
    assert "CERT_NONE" not in source
    assert "check_hostname = True" in source
