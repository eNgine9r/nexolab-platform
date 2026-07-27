from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from main import DeviceAgent, Settings


class DeviceAgentMQTTTLSIntegrationTests(unittest.TestCase):
    @patch("main.MQTTTLSConfig.from_environment")
    @patch("main.mqtt.Client")
    def test_tls_context_is_applied_before_client_setup(
        self,
        client_factory: Mock,
        tls_from_environment: Mock,
    ) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        database_path = Path(temporary_directory.name) / "edge.db"
        with patch.dict(
            os.environ,
            {"DATABASE_PATH": str(database_path)},
            clear=True,
        ):
            settings = Settings.from_env()

        client = client_factory.return_value
        tls_config = tls_from_environment.return_value

        def assert_before_logger(_client: Mock) -> None:
            self.assertIs(_client, client)
            client.enable_logger.assert_not_called()

        tls_config.apply.side_effect = assert_before_logger

        agent = DeviceAgent(settings)

        self.assertIs(agent.mqtt_tls, tls_config)
        tls_from_environment.assert_called_once_with()
        tls_config.apply.assert_called_once_with(client)
        client.enable_logger.assert_called_once()

    def test_main_source_has_no_tls_verification_bypass(self) -> None:
        source = (
            Path(__file__).resolve().parents[1] / "main.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("tls_insecure_set", source)
        self.assertNotIn("CERT_NONE", source)


if __name__ == "__main__":
    unittest.main()
