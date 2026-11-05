from __future__ import annotations

import unittest

from commissioning_preflight import CommissioningPreflightRequest, PROFILES, execute_preflight
from test_commissioning_preflight import FakeRuntime
from waveshare_8ai import Waveshare8AIReader


class WaveshareCommissioningTests(unittest.TestCase):
    def test_profile_contract_contains_only_fc03_fc04(self) -> None:
        profile = PROFILES["waveshare-8ai-b-v3"]
        request = CommissioningPreflightRequest(
            "edge-01", "rs485-main", "/dev/serial/by-id/usb-test", 1,
            profile.profile_id, profile.profile_version, 5.0,
        )
        result = execute_preflight(request, FakeRuntime())
        self.assertEqual(result["result"], "passed")
        self.assertEqual((result["read_method"], result["function_codes"]), ("modbus_rtu_fc03_fc04", [3, 4]))
        self.assertEqual(result["modbus_writes"], "none")

    def test_mode_and_raw_current_are_read_separately_without_writes(self) -> None:
        class Client:
            def __init__(self) -> None:
                self.calls = []
            def read_holding_registers(self, unit: int, address: int, count: int) -> tuple[int, ...]:
                self.calls.append((3, unit, address, count))
                return (3,)
            def read_input_registers(self, unit: int, address: int, count: int) -> tuple[int, ...]:
                self.calls.append((4, unit, address, count))
                return (12000,)
        client = Client()
        reading = Waveshare8AIReader(client).read_channel(1, 2)
        self.assertEqual((reading.mode_label, reading.value, reading.unit), ("4-20mA", 12000.0, "uA"))
        self.assertEqual(client.calls, [(3, 1, 0x1001, 1), (4, 1, 1, 1)])


if __name__ == "__main__":
    unittest.main()
