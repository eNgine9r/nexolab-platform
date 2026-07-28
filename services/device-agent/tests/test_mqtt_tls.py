from __future__ import annotations

import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mqtt_tls import MQTTTLSConfig


class MQTTTLSConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.ca_file = root / "ca.pem"
        self.certificate_file = root / "client.pem"
        self.key_file = root / "client.key"
        for path in (self.ca_file, self.certificate_file, self.key_file):
            path.write_text("test-material", encoding="utf-8")
            path.chmod(0o600)

    def test_disabled_mode_has_no_tls_material(self) -> None:
        config = MQTTTLSConfig.from_environment({})

        self.assertFalse(config.enabled)
        self.assertIsNone(config.ca_file)

    def test_disabled_mode_rejects_tls_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "MQTT_TLS_REQUIRED"):
            MQTTTLSConfig.from_environment(
                {"MQTT_TLS_CA_FILE": str(self.ca_file)}
            )

    def test_enabled_mode_requires_readable_ca(self) -> None:
        with self.assertRaisesRegex(ValueError, "MQTT_TLS_CA_FILE"):
            MQTTTLSConfig.from_environment({"MQTT_TLS_REQUIRED": "true"})

        with self.assertRaisesRegex(ValueError, "not readable"):
            MQTTTLSConfig.from_environment(
                {
                    "MQTT_TLS_REQUIRED": "true",
                    "MQTT_TLS_CA_FILE": str(
                        Path(self.temporary_directory.name) / "missing-ca.pem"
                    ),
                }
            )

    def test_client_certificate_and_key_are_atomic(self) -> None:
        for field, value in (
            ("MQTT_TLS_CERT_FILE", str(self.certificate_file)),
            ("MQTT_TLS_KEY_FILE", str(self.key_file)),
        ):
            with self.subTest(field=field):
                environment = {
                    "MQTT_TLS_REQUIRED": "true",
                    "MQTT_TLS_CA_FILE": str(self.ca_file),
                    field: value,
                }
                with self.assertRaisesRegex(ValueError, "configured together"):
                    MQTTTLSConfig.from_environment(environment)

    def test_enabled_mode_loads_complete_mtls_material(self) -> None:
        config = MQTTTLSConfig.from_environment(
            {
                "MQTT_TLS_REQUIRED": "true",
                "MQTT_TLS_CA_FILE": str(self.ca_file),
                "MQTT_TLS_CERT_FILE": str(self.certificate_file),
                "MQTT_TLS_KEY_FILE": str(self.key_file),
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.ca_file, self.ca_file)
        self.assertEqual(
            config.client_certificate_file,
            self.certificate_file,
        )
        self.assertEqual(config.client_key_file, self.key_file)

    @patch("mqtt_tls.ssl.create_default_context")
    def test_apply_requires_ca_hostname_and_tls12_or_newer(
        self,
        create_default_context: Mock,
    ) -> None:
        context = create_default_context.return_value
        client = Mock()
        config = MQTTTLSConfig.from_environment(
            {
                "MQTT_TLS_REQUIRED": "true",
                "MQTT_TLS_CA_FILE": str(self.ca_file),
                "MQTT_TLS_CERT_FILE": str(self.certificate_file),
                "MQTT_TLS_KEY_FILE": str(self.key_file),
            }
        )

        config.apply(client)

        create_default_context.assert_called_once_with(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=str(self.ca_file),
        )
        self.assertEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        context.load_cert_chain.assert_called_once_with(
            certfile=str(self.certificate_file),
            keyfile=str(self.key_file),
        )
        client.tls_set_context.assert_called_once_with(context)

    def test_source_contains_no_hostname_verification_bypass(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "mqtt_tls.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("tls_insecure_set", source)
        self.assertNotIn("CERT_NONE", source)
        self.assertIn("check_hostname = True", source)


if __name__ == "__main__":
    unittest.main()
