from __future__ import annotations

import unittest
from unittest.mock import Mock

from sdm120 import REGISTER_BY_KEY, SDM120Reader, decode_registers


class SDM120RecordedFrameTests(unittest.TestCase):
    def test_decodes_real_voltage_frame(self) -> None:
        reading = decode_registers(
            1,
            REGISTER_BY_KEY["voltage"],
            (17251, 51411),
        )
        self.assertEqual(reading.metric, "electrical.voltage")
        self.assertEqual(reading.unit, "V")
        self.assertEqual(reading.value, 227.8)
        self.assertEqual(reading.raw_value, (17251 << 16) | 51411)

    def test_decodes_real_frequency_frame(self) -> None:
        reading = decode_registers(
            1,
            REGISTER_BY_KEY["frequency"],
            (16968, 9607),
        )
        self.assertEqual(reading.value, 50.04)
        self.assertEqual(reading.unit, "Hz")
    def test_decodes_real_import_energy_frame(self) -> None:
        reading = decode_registers(
            1,
            REGISTER_BY_KEY["import_active_energy"],
            (15647, 48759),
        )
        self.assertEqual(reading.metric, "electrical.energy.active")
        self.assertEqual(reading.unit, "kWh")
        self.assertEqual(reading.value, 0.039)

    def test_reader_uses_exact_fc04_two_register_block(self) -> None:
        client = Mock()
        client.read_input_registers.return_value = (17251, 51411)
        reader = SDM120Reader(client)

        reading = reader.read_metric(1, "voltage")

        client.read_input_registers.assert_called_once_with(1, 0x0000, 2)
        self.assertEqual(reading.value, 227.8)

    def test_rejects_invalid_word_count_and_nonfinite_float(self) -> None:
        with self.assertRaisesRegex(ValueError, "expects 2"):
            decode_registers(1, REGISTER_BY_KEY["voltage"], (17251,))
        with self.assertRaisesRegex(ValueError, "finite"):
            decode_registers(1, REGISTER_BY_KEY["voltage"], (0x7F80, 0x0000))


if __name__ == "__main__":
    unittest.main()
