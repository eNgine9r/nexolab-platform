from __future__ import annotations

import unittest

from app.commissioning.preflight_client import DeviceAgentPreflightCommand, DeviceAgentPreflightError, validate_preflight_evidence
from app.commissioning.activation_client import DeviceAgentActivationCommand, DeviceAgentActivationError, validate_activation_evidence

PROFILE = "waveshare-8ai-b-v3"
VERSION = "waveshare-modbus-rtu-analog-input-8ch-b-v3-readonly-v1"
BUS = "commissioning-0123456789abcdef"
PATH = "/dev/serial/by-id/usb-analog"


class WaveshareEvidenceTests(unittest.TestCase):
    def test_preflight_must_prove_only_the_fixed_read_functions(self) -> None:
        command = DeviceAgentPreflightCommand("edge-01", BUS, PATH, 1, PROFILE, VERSION, 5.0)
        evidence = {"schema_version": 1, "result": "passed", "code": "preflight_passed",
                    "evidence_level": "partially_verified", **command.payload(),
                    "read_method": "modbus_rtu_fc03_fc04", "function_codes": [3, 4],
                    "checks": [], "observations": [], "warnings": [], "duration_ms": 1,
                    "modbus_writes": "none", "hardware_writes": "none"}
        self.assertEqual(validate_preflight_evidence(evidence, command)["function_codes"], [3, 4])
        for bad in ([3], [4, 3], [3, 4, 6]):
            with self.assertRaises(DeviceAgentPreflightError):
                validate_preflight_evidence({**evidence, "function_codes": bad}, command)

    def test_activation_rejects_wrong_protocol_and_writes(self) -> None:
        command = DeviceAgentActivationCommand("activation-1", "activate", "edge-01", BUS, PATH, 1, PROFILE, VERSION)
        evidence = {"schema_version": 1, "state": "active", **command.payload(), "device_id": "analog",
                    "target_ids": ["channel-1"], "registry_revision": 1,
                    "telemetry_source": "waveshare-analog-input-8ch-b-v3", "telemetry_equipment_id": f"WAVESHARE-8AI:{BUS}:1",
                    "polling_mode": "read_only_fc03_fc04", "modbus_writes": "none", "hardware_writes": "none"}
        self.assertEqual(validate_activation_evidence(evidence, command)["polling_mode"], "read_only_fc03_fc04")
        for change in ({"polling_mode": "read_only_fc04"}, {"hardware_writes": "present"}):
            with self.assertRaises(DeviceAgentActivationError):
                validate_activation_evidence({**evidence, **change}, command)


if __name__ == "__main__":
    unittest.main()
