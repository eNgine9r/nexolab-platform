from __future__ import annotations

import unittest

from modbus_rtu import (
    ModbusExceptionResponse,
    ModbusProtocolError,
    ModbusRTUClient,
    append_crc,
    build_read_holding_register_request,
    build_read_holding_registers_request,
    crc16,
    parse_read_holding_register_response,
    parse_read_holding_registers_response,
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


class SequencedSerial(FakeSerial):
    def __init__(self, responses: list[bytes], **kwargs: object) -> None:
        super().__init__(b"", **kwargs)
        self.responses = list(responses)

    def reset_input_buffer(self) -> None:
        self.response = bytearray(self.responses.pop(0) if self.responses else b"")


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

    def test_builds_bounded_block_request(self) -> None:
        expected = append_crc(bytes.fromhex("6a030100000c"))
        self.assertEqual(
            build_read_holding_registers_request(106, 256, 12),
            expected,
        )
        with self.assertRaisesRegex(ValueError, "1..125"):
            build_read_holding_registers_request(106, 256, 126)

    def test_parses_normal_response(self) -> None:
        frame = append_crc(bytes.fromhex("6a03020104"))
        self.assertEqual(parse_read_holding_register_response(frame, 106), 260)

    def test_parses_block_response(self) -> None:
        registers = (100, 0, 200, 1, 300, 2)
        payload = bytes((106, 0x03, len(registers) * 2)) + b"".join(
            value.to_bytes(2, byteorder="big") for value in registers
        )
        frame = append_crc(payload)
        self.assertEqual(
            parse_read_holding_registers_response(frame, 106, len(registers)),
            registers,
        )

    def test_rejects_crc_mismatch(self) -> None:
        frame = bytes.fromhex("6a030201049d00")
        with self.assertRaises(ModbusProtocolError):
            parse_read_holding_register_response(frame, 106)

    def test_rejects_unexpected_block_size(self) -> None:
        frame = append_crc(bytes.fromhex("6a030400010002"))
        with self.assertRaisesRegex(ModbusProtocolError, "frame length"):
            parse_read_holding_registers_response(frame, 106, 3)

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

    def test_client_reads_probe_block_in_one_fc03_transaction(self) -> None:
        registers = tuple(range(12))
        payload = bytes((106, 0x03, 24)) + b"".join(
            value.to_bytes(2, byteorder="big") for value in registers
        )
        fake = FakeSerial(append_crc(payload))
        client = ModbusRTUClient(
            "/dev/rs485",
            timeout=0.1,
            retries=0,
            serial_factory=lambda **kwargs: fake,
        )

        self.assertEqual(client.read_holding_registers(106, 256, 12), registers)
        self.assertEqual(
            fake.writes,
            [build_read_holding_registers_request(106, 256, 12)],
        )

    def test_observer_records_one_successful_physical_request(self) -> None:
        measurements = []
        response = append_crc(bytes.fromhex("6a03020104"))
        fake = FakeSerial(response)
        client = ModbusRTUClient(
            "/dev/serial/by-id/test",
            timeout=0.01,
            retries=0,
            serial_factory=lambda **kwargs: fake,
            request_observer=measurements.append,
        )

        with client.instrumentation_scope(
            device_family="xjp60d",
            target_id="106-03",
        ):
            self.assertEqual(client.read_holding_register(106, 260), 260)

        self.assertEqual(len(measurements), 1)
        measurement = measurements[0]
        self.assertEqual(measurement.bus, "/dev/serial/by-id/test")
        self.assertEqual(measurement.device_family, "xjp60d")
        self.assertEqual(measurement.target_id, "106-03")
        self.assertEqual(measurement.operation, "normal")
        self.assertEqual(measurement.unit_id, 106)
        self.assertEqual(measurement.function, 3)
        self.assertEqual(measurement.attempt, 1)
        self.assertEqual(measurement.outcome, "success")
        self.assertGreaterEqual(measurement.duration_seconds, 0)

    def test_timeout_retry_is_two_physical_attempts(self) -> None:
        measurements = []
        response = append_crc(bytes.fromhex("6a03020104"))
        fake = SequencedSerial([b"", response])
        client = ModbusRTUClient(
            "/dev/rs485",
            timeout=0.001,
            retries=1,
            serial_factory=lambda **kwargs: fake,
            request_observer=measurements.append,
        )

        self.assertEqual(client.read_holding_register(106, 260), 260)

        self.assertEqual(len(fake.writes), 2)
        self.assertEqual([item.attempt for item in measurements], [1, 2])
        self.assertEqual([item.outcome for item in measurements], ["timeout", "success"])

    def test_protocol_error_is_recorded_once_without_retry(self) -> None:
        measurements = []
        fake = FakeSerial(bytes.fromhex("6a030201049d00"))
        client = ModbusRTUClient(
            "/dev/rs485",
            timeout=0.01,
            retries=2,
            serial_factory=lambda **kwargs: fake,
            request_observer=measurements.append,
        )

        with self.assertRaises(ModbusProtocolError):
            client.read_holding_register(106, 260)

        self.assertEqual(len(fake.writes), 1)
        self.assertEqual(len(measurements), 1)
        self.assertEqual(measurements[0].outcome, "protocol_error")

    def test_observer_failure_does_not_interrupt_acquisition(self) -> None:
        response = append_crc(bytes.fromhex("6a03020104"))
        fake = FakeSerial(response)
        client = ModbusRTUClient(
            "/dev/rs485",
            timeout=0.01,
            retries=0,
            serial_factory=lambda **kwargs: fake,
            request_observer=lambda _measurement: (_ for _ in ()).throw(RuntimeError("metrics failed")),
        )

        self.assertEqual(client.read_holding_register(106, 260), 260)


if __name__ == "__main__":
    unittest.main()
