from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from main import AgentState, DeviceAgent, Settings, read_mounted_secret


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
NODE_ID = "edge-01"
USERNAME = f"node:{ORGANIZATION_ID}:{NODE_ID}"
CLIENT_ID = f"nexolab-{ORGANIZATION_ID}-{NODE_ID}"
PASSWORD = "nxl_edge_test_secret"


class SecureMQTTSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.password_file = Path(self.temporary_directory.name) / "password"
        self.password_file.write_text(PASSWORD, encoding="utf-8")
        self.password_file.chmod(0o600)

    def secure_environment(self) -> dict[str, str]:
        return {
            "NEXOLAB_NODE_ID": NODE_ID,
            "NEXOLAB_ORGANIZATION_ID": ORGANIZATION_ID,
            "MQTT_AUTH_REQUIRED": "true",
            "MQTT_PASSWORD_FILE": str(self.password_file),
            "DATABASE_PATH": str(
                Path(self.temporary_directory.name) / "edge.db"
            ),
        }

    def test_secure_identity_is_derived_exactly(self) -> None:
        with patch.dict(os.environ, self.secure_environment(), clear=True):
            settings = Settings.from_env()

        self.assertTrue(settings.mqtt_auth_required)
        self.assertEqual(settings.mqtt_username, USERNAME)
        self.assertEqual(settings.mqtt_client_id, CLIENT_ID)
        self.assertEqual(settings.mqtt_password_file, self.password_file)
        self.assertNotIn(PASSWORD, repr(settings))

    def test_secure_mode_requires_organization(self) -> None:
        environment = self.secure_environment()
        environment.pop("NEXOLAB_ORGANIZATION_ID")
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(
                ValueError,
                "NEXOLAB_ORGANIZATION_ID",
            ):
                Settings.from_env()

    def test_secure_mode_rejects_identity_drift(self) -> None:
        for field, value, message in (
            ("MQTT_USERNAME", "node:foreign:edge-01", "MQTT_USERNAME"),
            ("MQTT_CLIENT_ID", "foreign-client", "MQTT_CLIENT_ID"),
        ):
            with self.subTest(field=field):
                environment = self.secure_environment()
                environment[field] = value
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(ValueError, message):
                        Settings.from_env()

    def test_secure_mode_rejects_missing_or_invalid_secret(self) -> None:
        environment = self.secure_environment()
        environment["MQTT_PASSWORD_FILE"] = str(
            Path(self.temporary_directory.name) / "missing"
        )
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "not readable"):
                Settings.from_env()

        for value in ("", "contains whitespace", "bad\tsecret"):
            with self.subTest(value=value):
                self.password_file.write_text(value, encoding="utf-8")
                with patch.dict(
                    os.environ,
                    self.secure_environment(),
                    clear=True,
                ):
                    with self.assertRaises(ValueError):
                        Settings.from_env()

    def test_unsecured_mode_preserves_legacy_client_id(self) -> None:
        environment = {
            "NEXOLAB_NODE_ID": NODE_ID,
            "NEXOLAB_ORGANIZATION_ID": ORGANIZATION_ID,
            "MQTT_AUTH_REQUIRED": "false",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertFalse(settings.mqtt_auth_required)
        self.assertIsNone(settings.mqtt_username)
        self.assertEqual(settings.mqtt_client_id, NODE_ID)

    def test_unsecured_mode_rejects_password_configuration(self) -> None:
        environment = {
            "MQTT_AUTH_REQUIRED": "false",
            "MQTT_PASSWORD_FILE": str(self.password_file),
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(ValueError, "MQTT_AUTH_REQUIRED"):
                Settings.from_env()

    def test_trailing_newline_is_not_part_of_secret(self) -> None:
        self.password_file.write_text(PASSWORD + "\n", encoding="utf-8")
        self.assertEqual(
            read_mounted_secret(
                self.password_file,
                label="MQTT password",
            ),
            PASSWORD,
        )

    @patch("main.NodeOperationalPublisher")
    @patch("main.mqtt.Client")
    def test_device_agent_configures_paho_without_health_disclosure(
        self,
        client_factory: Mock,
        operational_factory: Mock,
    ) -> None:
        with patch.dict(os.environ, self.secure_environment(), clear=True):
            settings = Settings.from_env()

        client = client_factory.return_value
        agent = DeviceAgent(settings)

        self.assertEqual(
            client_factory.call_args.kwargs["client_id"],
            CLIENT_ID,
        )
        client.username_pw_set.assert_called_once_with(USERNAME, PASSWORD)
        snapshot = AgentState().snapshot(agent.queue.size(), settings)
        serialized = json.dumps(snapshot, sort_keys=True)
        self.assertNotIn(PASSWORD, serialized)
        self.assertNotIn(USERNAME, serialized)
        self.assertNotIn(str(self.password_file), serialized)
        operational_factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
