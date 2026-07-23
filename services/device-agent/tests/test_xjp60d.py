from __future__ import annotations

import unittest

from xjp60d import XJP60DReader, decode_reading, signed_int16


class FakeClient:
    def __init__(self, values: dict[tuple[int, int], int]) -> None:
        self.values = values
        self.requests: list[tuple[int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.requests.append((unit_id, address))
        return self.values[(unit_id, address)]


class XJP60DTests(unittest.TestCase):
    def test_decodes_valid_high_alarm(self) -> None:
        reading = decode_reading(106, 3, 260, 0x1102)
        self.assertEqual(reading.value, 26.0)
        self.assertEqual(reading.quality, "valid")
        self.assertEqual(reading.alarm, "high")

    def test_discards_probe_error_value(self) -> None:
        reading = decode_reading(101, 6, 471, 0x1103)
        self.assertIsNone(reading.value)
        self.assertEqual(reading.quality, "sensor_error")
        self.assertEqual(reading.alarm, "probe_error")

    def test_decodes_negative_signed_temperature(self) -> None:
        self.assertEqual(signed_int16(0xFF9C), -100)
        reading = decode_reading(106, 4, 0xFF9C, 0x1100)
        self.assertEqual(reading.value, -10.0)
        self.assertIsNone(reading.alarm)

    def test_reader_uses_separate_value_and_status_requests(self) -> None:
        client = FakeClient({(106, 260): 260, (106, 261): 0x1102})
        reading = XJP60DReader(client).read_channel(106, 3)
        self.assertEqual(reading.value, 26.0)
        self.assertEqual(client.requests, [(106, 260), (106, 261)])


if __name__ == "__main__":
    unittest.main()
