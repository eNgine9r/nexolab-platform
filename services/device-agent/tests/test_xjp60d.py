from __future__ import annotations

import unittest

from xjp60d import XJP60DReader, decode_reading, signed_int16


class FakeClient:
    def __init__(self, registers: dict[tuple[int, int], int]) -> None:
        self.registers = registers
        self.requests: list[tuple[int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.requests.append((unit_id, address))
        return self.registers[(unit_id, address)]


class FailingClient(FakeClient):
    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.requests.append((unit_id, address))
        raise RuntimeError("controller unavailable")


class XJP60DTests(unittest.TestCase):
    def test_decodes_valid_high_alarm(self) -> None:
        reading = decode_reading(106, 3, 260, 0x1102)
        self.assertEqual(reading.value, 26.0)
        self.assertEqual(reading.quality, "valid")
        self.assertEqual(reading.alarm, "high")

    def test_discards_probe_error_value_without_invalid_alarm(self) -> None:
        reading = decode_reading(101, 6, 471, 0x1103)
        self.assertIsNone(reading.value)
        self.assertEqual(reading.quality, "sensor_error")
        self.assertIsNone(reading.alarm)
        self.assertEqual(reading.raw_status, 0x1103)

    def test_decodes_negative_signed_temperature(self) -> None:
        self.assertEqual(signed_int16(0xFF9C), -100)
        reading = decode_reading(106, 4, 0xFF9C, 0x1100)
        self.assertEqual(reading.value, -10.0)
        self.assertIsNone(reading.alarm)

    def test_reader_uses_controller_compatible_single_register_requests(self) -> None:
        client = FakeClient({(106, 260): 260, (106, 261): 0x1102})

        reading = XJP60DReader(client).read_channel(106, 3)

        self.assertEqual(client.requests, [(106, 260), (106, 261)])
        self.assertEqual(reading.value, 26.0)
        self.assertEqual(reading.alarm, "high")

    def test_reader_reads_all_inputs_only_when_explicitly_requested(self) -> None:
        values = (100, 200, 260, 0xFF9C, 500, 600)
        statuses = (0x1100, 0x1103, 0x1102, 0x1100, 0x1101, 0x1100)
        registers: dict[tuple[int, int], int] = {}
        for channel, (value, status) in enumerate(zip(values, statuses, strict=True), start=1):
            start = 256 + (channel - 1) * 2
            registers[(126, start)] = value
            registers[(126, start + 1)] = status
        client = FakeClient(registers)

        readings = XJP60DReader(client).read_all_channels(126)

        self.assertEqual(len(client.requests), 12)
        self.assertEqual([item.channel for item in readings], [1, 2, 3, 4, 5, 6])
        self.assertEqual(readings[0].value, 10.0)
        self.assertIsNone(readings[1].value)
        self.assertEqual(readings[1].quality, "sensor_error")
        self.assertEqual(readings[2].alarm, "high")
        self.assertEqual(readings[3].value, -10.0)
        self.assertEqual(readings[4].alarm, "low")
        self.assertEqual(readings[5].value, 60.0)

    def test_does_not_cache_controller_failures(self) -> None:
        client = FailingClient({})
        reader = XJP60DReader(client)

        with self.assertRaisesRegex(RuntimeError, "controller unavailable"):
            reader.read_channel(138, 1)
        with self.assertRaisesRegex(RuntimeError, "controller unavailable"):
            reader.read_channel(138, 6)

        self.assertEqual(client.requests, [(138, 256), (138, 266)])


if __name__ == "__main__":
    unittest.main()
