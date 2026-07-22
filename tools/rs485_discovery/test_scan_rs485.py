from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def load_module(name: str, filename: str):
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scan_rs485 = load_module("scan_rs485", "scan_rs485.py")
verify_candidates = load_module("verify_candidates", "verify_candidates.py")


class ModbusFrameTests(unittest.TestCase):
    def test_crc_known_request(self) -> None:
        payload = bytes.fromhex("010300000001")
        self.assertEqual(scan_rs485.crc16_modbus(payload), 0x0A84)
        self.assertEqual(scan_rs485.add_crc(payload).hex(), "010300000001840a")

    def test_extract_register_response_from_noise(self) -> None:
        response = bytes.fromhex("0103021234b533")
        extracted = scan_rs485.extract_response(b"noise" + response, 1, 3)
        self.assertEqual(extracted, response)
        registers, exception = scan_rs485.decode_register_response(response)
        self.assertEqual(registers, [0x1234])
        self.assertIsNone(exception)

    def test_extract_exception_response(self) -> None:
        response = scan_rs485.add_crc(bytes((1, 0x83, 0x02)))
        self.assertEqual(scan_rs485.extract_response(response, 1, 3), response)
        registers, exception = scan_rs485.decode_register_response(response)
        self.assertEqual(registers, [])
        self.assertEqual(exception, 0x02)

    def test_parse_unit_ranges(self) -> None:
        self.assertEqual(scan_rs485.parse_id_spec("1-3,7,10-9"), [1, 2, 3, 7, 9, 10])
        with self.assertRaises(ValueError):
            scan_rs485.parse_id_spec("0,248")

    def test_identity_preferred_over_fingerprint(self) -> None:
        result = scan_rs485.identify_device(
            {"vendor_name": "Dixell", "product_code": "XJP60D"},
            {"registers_256": [200, 210, 220]},
        )
        self.assertEqual(result[0], "dixell-xjp60d")
        self.assertEqual(result[2], 1.0)

    def test_strict_verifier_accepts_exact_register_count(self) -> None:
        response = verify_candidates.add_crc(bytes.fromhex("0103021234"))
        extracted = verify_candidates.extract_strict_response(response, 1, 3, 1)
        self.assertEqual(extracted, response)

    def test_strict_verifier_rejects_zero_byte_read(self) -> None:
        malformed = verify_candidates.add_crc(bytes.fromhex("c80300"))
        extracted = verify_candidates.extract_strict_response(malformed, 200, 3, 1)
        self.assertIsNone(extracted)

    def test_strict_verifier_accepts_exception(self) -> None:
        response = verify_candidates.add_crc(bytes((1, 0x83, 0x02)))
        extracted = verify_candidates.extract_strict_response(response, 1, 3, 1)
        self.assertEqual(extracted, response)


if __name__ == "__main__":
    unittest.main()
