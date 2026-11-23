from __future__ import annotations

import struct
import unittest

from commissioning_preflight import CommissioningPreflightRequest, execute_preflight
from sdm120 import SDM120Reader
from test_commissioning_preflight import FakeRuntime


class MeterPreflightTests(unittest.TestCase):
    def test_profile_uses_fc04_contract(self) -> None:
        from commissioning_preflight import PROFILES

        profile = PROFILES["eastron-sdm120m"]
        self.assertTrue(profile.activation_supported)
        request = CommissioningPreflightRequest(
            "edge-01", "rs485-main", "/dev/serial/by-id/usb-test", 1,
            profile.profile_id, profile.profile_version, 5.0,
        )
        runtime = FakeRuntime()
        result = execute_preflight(request, runtime)
        self.assertEqual(result["result"], "passed")
        self.assertEqual((result["read_method"], result["function_codes"]), ("modbus_rtu_fc04", [4]))
        self.assertEqual(runtime.read_calls[0][0], profile.profile_id)
        self.assertEqual(result["modbus_writes"], "none")

    def test_meter_reader_uses_input_registers_and_rejects_nonfinite_value(self) -> None:
        class InputOnly:
            def __init__(self) -> None:
                self.calls = []

            def read_input_registers(self, unit_id: int, address: int, count: int) -> tuple[int, ...]:
                self.calls.append((unit_id, address, count))
                value = 230.0 if address == 0 else float("nan")
                return struct.unpack(">HH", struct.pack(">f", value))

        client = InputOnly()
        reader = SDM120Reader(client)
        self.assertEqual(reader.read_metric(3, "voltage").value, 230.0)
        with self.assertRaises(RuntimeError):
            reader.read_metric(3, "frequency")
        self.assertEqual(client.calls, [(3, 0, 2), (3, 0x46, 2)])


if __name__ == "__main__":
    unittest.main()
