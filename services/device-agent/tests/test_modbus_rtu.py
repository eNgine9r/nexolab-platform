from __future__ import annotations

import unittest

from modbus_rtu import (
    ModbusExceptionResponse,
    ModbusProtocolError,
    ModbusRTUClient,
    append_crc,
    build_read_holding_register_request,
    crc16,
    parse_read_holding_register_response,
)


class FakeSerial:
    def __init__(self, response: bytes, **_: object) -> None:
        self.response = bytearray(response)
        self.writes: list[bytes] = []
        self.timeout = 0.1
        self.closed = False

    def reset_input_buffer(self) -> None:
        pass

    def reset_output_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        result = bytes(self.response[:size])
        del self.response[:size]
        return result

    def close(self) -> None:
        self.closed = True


class ModbusRTUTests(unittest.TestCase):
    def test_crc_matches_known_request(self) -> None:
        payload = bytes.fromhex("6a0301040001")
        self.assertEqual(crc16(payload), 0xECCC)
        self.assertEqual(append_crc(payload), bytes.fromhex("6a0301040001ccec"))

    def test_builds_one_register_request(self) -> None:
        self.assertEqual(
            build_read_holding_register_request(106, 260),
            bytes.fromhex("6a0301040001ccec"),
        )

    def test_parses_normal_response(self) -> None:
        frame = append_crc(bytes.fromhex("6a03020104"))
        self.assertEqual(parse_read_holding_register_response(frame, 106), 260)

    def test_rejects_crc_mismatch(self) -> None:
        frame = bytes.fromhex("6a030201049d00")
        with self.assertRaises(ModbusProtocolError):
            parse_read_holding_register_response(frame, 106)

    def test_raises_modbus_exception(self) -> None:
        frame = append_crc(bytes((106, 0x83, 0x03)))
        with self.assertRaises(ModbusExceptionResponse) as context:
            parse_read_holding_register_response(frame, 106)
        self.assertEqual(context.exception.exception_code, 3)

    def test_client_reads_one_register(self) -> None:
        response = append_crc(bytes.fromhex("6a03020104"))
        fake = FakeSerial(response)
        client = ModbusRTUClient(
            "/dev/rs485",
            timeout=0.1,
            retries=0,
            serial_factory=lambda **kwargs: fake,
        )
        self.assertEqual(client.read_holding_register(106, 260), 260)
        self.assertEqual(fake.writes, [bytes.fromhex("6a0301040001ccec")])
        client.close()
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
