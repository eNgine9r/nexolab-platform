from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from main import DeviceAgent, Settings


class SimulatorTelemetryContractTests(unittest.TestCase):
    def test_simulator_emits_canonical_asset_identity(self) -> None:
        with patch.dict(
            os.environ,
            {
                "NEXOLAB_NODE_ID": "edge-01",
                "DEVICE_MODE": "simulator",
            },
            clear=True,
        ):
            settings = Settings.from_env()

        agent = object.__new__(DeviceAgent)
        agent.settings = settings
        records, error = DeviceAgent.sample_batch(agent)

        self.assertIsNone(error)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].equipment_id, "SIM-edge-01")
        self.assertEqual(records[0].channel_id, "ambient-temperature")
        self.assertEqual(records[0].quality, "valid")


if __name__ == "__main__":
    unittest.main()
