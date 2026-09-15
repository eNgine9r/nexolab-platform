from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from akcc25 import (
    CONTROL_STATES,
    PROFILE_VERSION,
    REGISTER_BY_KEY,
    AKCC25ProReader,
    decode_register,
)


class FakeReader:
    def __init__(self, values: dict[int, int]) -> None:
        self.values = values
        self.calls: list[tuple[int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.calls.append((unit_id, address))
        return self.values[address]


class AKCC25ProDecoderTests(unittest.TestCase):
    def test_profile_is_exact_sw13x_fc03_contract(self) -> None:
        self.assertEqual(PROFILE_VERSION, "danfoss-ak-cc25-pro-sw1.3x-fc03-v1")
        expected = {
            "control_state": (2007, 2006),
            "compressor_state": (2510, 2509),
            "compressor_speed": (2685, 2684),
            "fan_state": (2511, 2510),
            "defrost_state": (2512, 2511),
            "network_status": (2682, 2681),
            "alarm_status": (2541, 2540),
            "network_address": (2008, 2007),
            "baudrate_setting": (2251, 2250),
            "parity_setting": (2255, 2254),
        }
        for key, (adu, pdu) in expected.items():
            self.assertEqual(REGISTER_BY_KEY[key].adu_address, adu)
            self.assertEqual(REGISTER_BY_KEY[key].address, pdu)

    def test_documented_control_state_is_decoded_without_inference(self) -> None:
        reading = decode_register(35, REGISTER_BY_KEY["control_state"], 14)
        self.assertEqual((reading.value, reading.semantic, reading.quality), (14.0, "defrost", "valid"))
        self.assertEqual(CONTROL_STATES[0], "normal_control")

    def test_unlisted_control_state_fails_closed(self) -> None:
        reading = decode_register(35, REGISTER_BY_KEY["control_state"], 13)
        self.assertIsNone(reading.value)
        self.assertIsNone(reading.semantic)
        self.assertEqual(reading.quality, "unknown")

    def test_binary_and_percent_ranges_fail_closed(self) -> None:
        compressor = decode_register(35, REGISTER_BY_KEY["compressor_state"], 1)
        self.assertEqual((compressor.value, compressor.semantic, compressor.quality), (1.0, "on", "valid"))
        speed = decode_register(35, REGISTER_BY_KEY["compressor_speed"], 73)
        self.assertEqual((speed.value, speed.unit, speed.quality), (73.0, "%", "valid"))
        fan = decode_register(35, REGISTER_BY_KEY["fan_state"], 1)
        self.assertEqual((fan.value, fan.semantic, fan.quality), (1.0, "on", "valid"))
        invalid_binary = decode_register(35, REGISTER_BY_KEY["defrost_state"], 2)
        self.assertEqual((invalid_binary.value, invalid_binary.quality), (None, "unknown"))
        network = decode_register(35, REGISTER_BY_KEY["network_status"], 100)
        self.assertEqual((network.value, network.unit, network.quality), (100.0, "%", "valid"))
        invalid_network = decode_register(35, REGISTER_BY_KEY["network_status"], 101)
        self.assertEqual((invalid_network.value, invalid_network.quality), (None, "unknown"))

    def test_documented_serial_settings_decode_without_writes(self) -> None:
        address = decode_register(35, REGISTER_BY_KEY["network_address"], 35)
        auto = decode_register(35, REGISTER_BY_KEY["baudrate_setting"], 1)
        parity = decode_register(35, REGISTER_BY_KEY["parity_setting"], 1)
        self.assertEqual((address.value, address.quality), (35.0, "valid"))
        self.assertEqual((auto.value, auto.semantic), (1.0, "auto"))
        self.assertEqual((parity.value, parity.semantic), (1.0, "even"))
        disabled = decode_register(35, REGISTER_BY_KEY["network_address"], 0xFFFF)
        self.assertEqual((disabled.value, disabled.quality), (-1.0, "valid"))

    def test_reader_uses_only_single_fc03_register_read_contract(self) -> None:
        client = FakeReader({2006: 0, 2509: 1})
        reader = AKCC25ProReader(client)
        state = reader.read_metric(35, "control_state")
        compressor = reader.read_metric(35, "compressor_state")
        self.assertEqual(state.semantic, "normal_control")
        self.assertEqual(compressor.semantic, "on")
        self.assertEqual(client.calls, [(35, 2006), (35, 2509)])

    def test_invalid_unit_and_unknown_metric_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Modbus unit ID"):
            decode_register(0, REGISTER_BY_KEY["control_state"], 0)
        with self.assertRaisesRegex(ValueError, "Unknown AK-CC25 Pro metric key"):
            AKCC25ProReader(FakeReader({})).read_metric(35, "setpoint")


if __name__ == "__main__":
    unittest.main()
