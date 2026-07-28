from __future__ import annotations

import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MQTTTLSSettings(Protocol):
    mqtt_tls_required: bool
    mqtt_tls_ca_file: str | None
    mqtt_tls_cert_file: str | None
    mqtt_tls_key_file: str | None


class TLSContextClient(Protocol):
    def tls_set_context(self, context: ssl.SSLContext) -> None: ...


@dataclass(frozen=True, slots=True)
class MQTTTLSConfig:
    enabled: bool
    ca_file: Path | None = None
    client_certificate_file: Path | None = None
    client_key_file: Path | None = None

    @classmethod
    def from_settings(cls, settings: MQTTTLSSettings) -> "MQTTTLSConfig":
        ca_file = _optional_path(settings.mqtt_tls_ca_file)
        certificate_file = _optional_path(settings.mqtt_tls_cert_file)
        key_file = _optional_path(settings.mqtt_tls_key_file)

        if not settings.mqtt_tls_required:
            if any(
                path is not None
                for path in (ca_file, certificate_file, key_file)
            ):
                raise RuntimeError(
                    "MQTT TLS files require MQTT_TLS_REQUIRED=true"
                )
            return cls(enabled=False)

        if ca_file is None:
            raise RuntimeError(
                "MQTT_TLS_CA_FILE is required when MQTT_TLS_REQUIRED=true"
            )
        _require_readable_file(ca_file, label="MQTT TLS CA")

        if (certificate_file is None) != (key_file is None):
            raise RuntimeError(
                "MQTT_TLS_CERT_FILE and MQTT_TLS_KEY_FILE must be configured together"
            )
        if certificate_file is not None and key_file is not None:
            _require_readable_file(
                certificate_file,
                label="MQTT TLS client certificate",
            )
            _require_readable_file(key_file, label="MQTT TLS client key")

        return cls(
            enabled=True,
            ca_file=ca_file,
            client_certificate_file=certificate_file,
            client_key_file=key_file,
        )

    def build_context(self) -> ssl.SSLContext:
        if not self.enabled or self.ca_file is None:
            raise RuntimeError("MQTT TLS configuration is not enabled")

        context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=str(self.ca_file),
        )
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = True
        if (
            self.client_certificate_file is not None
            and self.client_key_file is not None
        ):
            context.load_cert_chain(
                certfile=str(self.client_certificate_file),
                keyfile=str(self.client_key_file),
            )
        return context

    def apply(self, client: TLSContextClient) -> None:
        if self.enabled:
            client.tls_set_context(self.build_context())


def _optional_path(value: str | None) -> Path | None:
    normalized = (value or "").strip()
    return Path(normalized) if normalized else None


def _require_readable_file(path: Path, *, label: str) -> None:
    if not path.is_file() or not os.access(path, os.R_OK):
        raise RuntimeError(f"{label} file is not readable")
