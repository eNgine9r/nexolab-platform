from __future__ import annotations

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from embraco import (
    ALARM_BITS,
    CONTROL_STATES,
    REGISTER_BY_KEY,
    RELAY_BITS,
    EmbracoSyncReader,
    active_bits,
    decode_register,
)


class FakeReader:
    def __init__(self, values: dict[int, int]) -> None:
        self.values = values
        self.calls: list[tuple[int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.calls.append((unit_id, address))
        return self.values[address]


class EmbracoDecoderTests(unittest.TestCase):
    def test_verified_state_speed_and_bitfields_are_valid(self) -> None:
        state = decode_register(2, REGISTER_BY_KEY["control_state"], 5)
        speed = decode_register(2, REGISTER_BY_KEY["compressor_speed"], 4500)
        relays = decode_register(2, REGISTER_BY_KEY["relay_state_bits"], 11)
        alarms = decode_register(2, REGISTER_BY_KEY["alarm_state_bits"], 0)
        self.assertEqual((state.value, state.semantic, state.quality), (5.0, "pulldown", "valid"))
        self.assertEqual((speed.value, speed.unit, speed.quality), (4500.0, "rpm", "valid"))
        self.assertEqual(relays.value, 11.0)
        self.assertEqual(alarms.value, 0.0)

    def test_unverified_temperature_scale_fails_closed(self) -> None:
        reading = decode_register(2, REGISTER_BY_KEY["cabinet_temperature"], 1678)
        self.assertIsNone(reading.value)
        self.assertEqual(reading.quality, "unknown")
        self.assertEqual(reading.raw_value, 1678)

    def test_explicit_verified_scale_can_decode_signed_temperature(self) -> None:
        reading = decode_register(2, REGISTER_BY_KEY["evaporator_temperature"], 0xFF9C, temperature_scale=0.01)
        self.assertAlmostEqual(reading.value or 0, -1.0)
        self.assertEqual(reading.quality, "valid")

    def test_invalid_state_and_negative_speed_are_unknown_without_an_invented_upper_bound(self) -> None:
        self.assertEqual(decode_register(2, REGISTER_BY_KEY["control_state"], 99).quality, "unknown")
        high_speed = decode_register(2, REGISTER_BY_KEY["compressor_speed"], 9000)
        self.assertEqual((high_speed.value, high_speed.quality), (9000.0, "valid"))
        self.assertEqual(decode_register(2, REGISTER_BY_KEY["compressor_speed"], 0xFFFF).quality, "unknown")

    def test_manual_bit_maps_decode_without_register_writes(self) -> None:
        self.assertEqual(active_bits(11, RELAY_BITS), ("relay_1", "relay_2", "relay_4"))
        alarm_mask = (1 << 1) | (1 << 6) | (1 << 9)
        self.assertEqual(
            active_bits(alarm_mask, ALARM_BITS),
            ("high_cabinet_temperature", "open_door", "defrost_incomplete"),
        )
        self.assertEqual(CONTROL_STATES[3], "defrost")

    def test_reader_uses_one_fc03_register_read_for_requested_metric(self) -> None:
        client = FakeReader({11: 4500})
        reader = EmbracoSyncReader(client)
        result = reader.read_metric(2, "compressor_speed")
        self.assertEqual(result.value, 4500.0)
        self.assertEqual(client.calls, [(2, 11)])


if __name__ == "__main__":
    unittest.main()
