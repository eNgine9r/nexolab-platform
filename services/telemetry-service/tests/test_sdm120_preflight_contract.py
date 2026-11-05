from __future__ import annotations

import unittest

from app.commissioning.preflight_client import (
    DeviceAgentPreflightCommand,
    DeviceAgentPreflightError,
    validate_preflight_evidence,
)
from app.commissioning.activation_client import (
    DeviceAgentActivationCommand,
    DeviceAgentActivationError,
    validate_activation_evidence,
)


class MeterEvidenceTests(unittest.TestCase):
    def test_only_matching_profile_may_report_fc04(self) -> None:
        command = DeviceAgentPreflightCommand(
            "edge-01", "bus", "/dev/serial/by-id/usb-meter", 1,
            "eastron-sdm120m", "eastron-sdm120m-fc04-v1", 5.0,
        )
        evidence = {
            "schema_version": 1, "result": "passed", "code": "preflight_passed",
            "evidence_level": "partially_verified", **command.payload(),
            "read_method": "modbus_rtu_fc04", "function_codes": [4],
            "checks": [], "observations": [], "warnings": [], "duration_ms": 1,
            "modbus_writes": "none", "hardware_writes": "none",
        }
        validated = validate_preflight_evidence(evidence, command)
        self.assertEqual((validated["read_method"], validated["function_codes"]), ("modbus_rtu_fc04", [4]))
        for change in ({"function_codes": [3]}, {"function_codes": [6]}, {"read_method": "modbus_rtu_fc03"}):
            with self.assertRaises(DeviceAgentPreflightError):
                validate_preflight_evidence({**evidence, **change}, command)

    def test_activation_fc04_is_exactly_profile_scoped(self) -> None:
        command = DeviceAgentActivationCommand(
            "activation-1", "activate", "edge-01", "commissioning-0123456789abcdef",
            "/dev/serial/by-id/usb-meter", 1, "eastron-sdm120m", "eastron-sdm120m-fc04-v1",
        )
        evidence = {
            "schema_version": 1, "state": "active", **command.payload(),
            "device_id": "sdm120-commissioning-0123456789abcdef-1",
            "target_ids": ["target"], "registry_revision": 1,
            "telemetry_source": "eastron-sdm120m",
            "telemetry_equipment_id": "SDM120M:commissioning-0123456789abcdef:1",
            "polling_mode": "read_only_fc04", "modbus_writes": "none", "hardware_writes": "none",
        }
        self.assertEqual(validate_activation_evidence(evidence, command)["polling_mode"], "read_only_fc04")
        with self.assertRaises(DeviceAgentActivationError):
            validate_activation_evidence({**evidence, "polling_mode": "read_only_fc03"}, command)
        with self.assertRaises(DeviceAgentActivationError):
            validate_activation_evidence({**evidence, "modbus_writes": "present"}, command)


if __name__ == "__main__":
    unittest.main()
