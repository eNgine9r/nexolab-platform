from __future__ import annotations

import unittest
from unittest.mock import Mock

from modbus_rtu import (
    parse_read_holding_registers_response,
    parse_read_input_registers_response,
)
from waveshare_8ai import MODES, Waveshare8AIReader, decode_channel


class Waveshare8AITests(unittest.TestCase):
    def test_decodes_discovered_mode_zero_zero_input(self) -> None:
        reading = decode_channel(1, 1, mode_word=0, input_word=0)
        self.assertEqual(reading.mode_label, "0-10V")
        self.assertEqual(reading.metric, "analog.voltage")
        self.assertEqual(reading.unit, "mV")
        self.assertEqual(reading.raw_value, 0)
        self.assertEqual(reading.value, 0.0)

    def test_mode_table_preserves_vendor_physical_units(self) -> None:
        self.assertEqual((MODES[0].metric, MODES[0].unit), ("analog.voltage", "mV"))
        self.assertEqual((MODES[1].metric, MODES[1].unit), ("analog.voltage", "mV"))
        self.assertEqual((MODES[2].metric, MODES[2].unit), ("analog.current", "uA"))
        self.assertEqual((MODES[3].metric, MODES[3].unit), ("analog.current", "uA"))
        self.assertEqual((MODES[4].metric, MODES[4].unit), ("analog.adc_code", "count"))

    def test_recorded_issue_1125_frames_decode_all_eight_channels(self) -> None:
        mode_frame = bytes.fromhex(
            "01 03 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 e4 59"
        )
        input_frame = bytes.fromhex(
            "01 04 10 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 55 2c"
        )

        modes = parse_read_holding_registers_response(mode_frame, 1, 8)
        inputs = parse_read_input_registers_response(input_frame, 1, 8)

        self.assertEqual(modes, (0,) * 8)
        self.assertEqual(inputs, (0,) * 8)
        decoded = [
            decode_channel(1, channel, mode_word=modes[channel - 1], input_word=inputs[channel - 1])
            for channel in range(1, 9)
        ]
        self.assertTrue(all(item.mode == 0 for item in decoded))
        self.assertTrue(all(item.metric == "analog.voltage" for item in decoded))
        self.assertTrue(all(item.value == 0.0 and item.unit == "mV" for item in decoded))

    def test_reader_uses_fc03_mode_then_fc04_input_for_exact_channel(self) -> None:
        client = Mock()
        client.read_holding_registers.return_value = (3,)
        client.read_input_registers.return_value = (12500,)
        reading = Waveshare8AIReader(client).read_channel(1, 4)
        client.read_holding_registers.assert_called_once_with(1, 0x1003, 1)
        client.read_input_registers.assert_called_once_with(1, 0x0003, 1)
        self.assertEqual(reading.metric, "analog.current")
        self.assertEqual(reading.unit, "uA")
        self.assertEqual(reading.value, 12500.0)

    def test_channel_one_and_eight_preserve_register_ordering(self) -> None:
        for channel, mode_address, input_address in (
            (1, 0x1000, 0x0000),
            (8, 0x1007, 0x0007),
        ):
            with self.subTest(channel=channel):
                client = Mock()
                client.read_holding_registers.return_value = (0,)
                client.read_input_registers.return_value = (1234,)

                reading = Waveshare8AIReader(client).read_channel(1, channel)

                client.read_holding_registers.assert_called_once_with(
                    1, mode_address, 1
                )
                client.read_input_registers.assert_called_once_with(
                    1, input_address, 1
                )
                self.assertEqual(reading.channel, channel)
                self.assertEqual(reading.raw_value, 1234)

    def test_rejects_unknown_mode_and_invalid_channel(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported Waveshare input mode"):
            decode_channel(1, 1, mode_word=9, input_word=1)
        with self.assertRaisesRegex(ValueError, "channel must be"):
            decode_channel(1, 9, mode_word=0, input_word=0)

    def test_reader_converts_invalid_payload_to_runtime_error(self) -> None:
        client = Mock()
        client.read_holding_registers.return_value = (9,)
        client.read_input_registers.return_value = (0,)
        with self.assertRaisesRegex(RuntimeError, "invalid channel payload"):
            Waveshare8AIReader(client).read_channel(1, 1)

    def test_reader_never_exposes_write_method(self) -> None:
        client = Mock()
        reader = Waveshare8AIReader(client)
        self.assertFalse(hasattr(reader, "write_channel"))
        self.assertFalse(hasattr(reader, "set_mode"))


if __name__ == "__main__":
    unittest.main()
