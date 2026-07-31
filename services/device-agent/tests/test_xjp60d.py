from __future__ import annotations

import unittest

from xjp60d import XJP60DReader, decode_reading, signed_int16


class FakeClient:
    def __init__(self, registers: tuple[int, ...]) -> None:
        self.registers = registers
        self.requests: list[tuple[int, int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        raise AssertionError("single-register reads must not be used for XJP60D snapshots")

    def read_holding_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]:
        self.requests.append((unit_id, address, count))
        return self.registers


class FailingClient(FakeClient):
    def read_holding_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]:
        self.requests.append((unit_id, address, count))
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

    def test_reader_discovers_all_six_inputs_with_one_block_read(self) -> None:
        registers = (
            100,
            0x1100,
            200,
            0x1103,
            260,
            0x1102,
            0xFF9C,
            0x1100,
            500,
            0x1101,
            600,
            0x1100,
        )
        client = FakeClient(registers)
        readings = XJP60DReader(client).read_all_channels(126)

        self.assertEqual(client.requests, [(126, 256, 12)])
        self.assertEqual([item.channel for item in readings], [1, 2, 3, 4, 5, 6])
        self.assertEqual(readings[0].value, 10.0)
        self.assertIsNone(readings[1].value)
        self.assertEqual(readings[1].quality, "sensor_error")
        self.assertIsNone(readings[1].alarm)
        self.assertEqual(readings[2].alarm, "high")
        self.assertEqual(readings[3].value, -10.0)
        self.assertEqual(readings[4].alarm, "low")
        self.assertEqual(readings[5].value, 60.0)

    def test_reuses_controller_snapshot_for_sequential_channel_reads(self) -> None:
        registers = (100, 0, 200, 0, 300, 0, 400, 0, 500, 0, 600, 0)
        client = FakeClient(registers)
        reader = XJP60DReader(client, snapshot_ttl_seconds=1.0)

        self.assertEqual(reader.read_channel(106, 3).value, 30.0)
        self.assertEqual(reader.read_channel(106, 4).value, 40.0)
        self.assertEqual(client.requests, [(106, 256, 12)])

    def test_caches_controller_failure_for_remaining_inputs(self) -> None:
        client = FailingClient(tuple(range(12)))
        reader = XJP60DReader(client, snapshot_ttl_seconds=1.0)

        with self.assertRaisesRegex(RuntimeError, "controller unavailable"):
            reader.read_channel(138, 1)
        with self.assertRaisesRegex(RuntimeError, "controller unavailable"):
            reader.read_channel(138, 6)

        self.assertEqual(client.requests, [(138, 256, 12)])


if __name__ == "__main__":
    unittest.main()
