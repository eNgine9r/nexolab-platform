from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("profile_registers.py")
SPEC = importlib.util.spec_from_file_location("profile_registers", MODULE_PATH)
assert SPEC and SPEC.loader
profile_registers = importlib.util.module_from_spec(SPEC)
sys.modules["profile_registers"] = profile_registers
SPEC.loader.exec_module(profile_registers)


class RegisterProfilerTests(unittest.TestCase):
    def test_parse_range_spec(self) -> None:
        self.assertEqual(
            profile_registers.parse_range_spec(
                "3-1,7,9-10",
                0,
                20,
                "values",
            ),
            [1, 2, 3, 7, 9, 10],
        )
        with self.assertRaises(ValueError):
            profile_registers.parse_range_spec("21", 0, 20, "values")

    def test_one_register_request(self) -> None:
        request = profile_registers.build_read_request(200, 3, 0)
        self.assertEqual(request.hex(), "c803000000019593")
        with self.assertRaises(ValueError):
            profile_registers.build_read_request(200, 3, 0, count=2)

    def test_strict_response_accepts_one_register(self) -> None:
        response = profile_registers.add_crc(bytes.fromhex("c8030208fb"))
        extracted = profile_registers.extract_strict_response(response, 200, 3)
        self.assertEqual(extracted, response)

    def test_strict_response_rejects_wrong_byte_count(self) -> None:
        malformed = profile_registers.add_crc(bytes.fromhex("c80300"))
        self.assertIsNone(
            profile_registers.extract_strict_response(malformed, 200, 3)
        )

    def test_summary_marks_dynamic_register(self) -> None:
        rows = [
            profile_registers.Sample(
                unit_id=200,
                function=3,
                address=0,
                sample_index=0,
                outcome="value",
                value_u16=2299,
                value_s16=2299,
                exception_code=None,
                raw_hex="",
                elapsed_ms=1.0,
            ),
            profile_registers.Sample(
                unit_id=200,
                function=3,
                address=0,
                sample_index=1,
                outcome="value",
                value_u16=2301,
                value_s16=2301,
                exception_code=None,
                raw_hex="",
                elapsed_ms=1.0,
            ),
        ]
        summary = profile_registers.summarize(rows)
        self.assertEqual(len(summary), 1)
        self.assertTrue(summary[0]["changed"])
        self.assertFalse(summary[0]["stable"])
        self.assertEqual(summary[0]["minimum_u16"], 2299)
        self.assertEqual(summary[0]["maximum_u16"], 2301)


if __name__ == "__main__":
    unittest.main()
