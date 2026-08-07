from __future__ import annotations

import unittest

from modbus_rtu import ModbusRTUClient, append_crc


class RecoverySerial:
    def __init__(
        self,
        response: bytes = b"",
        *,
        fail_reset: bool = False,
        fail_write: bool = False,
        fail_close: bool = False,
    ) -> None:
        self.response = bytearray(response)
        self.fail_reset = fail_reset
        self.fail_write = fail_write
        self.fail_close = fail_close
        self.timeout = 0.01
        self.closed = False
        self.close_attempted = False
        self.reset_calls = 0
        self.writes: list[bytes] = []

    def reset_input_buffer(self) -> None:
        self.reset_calls += 1
        if self.fail_reset:
            raise OSError(5, "Input/output error")

    def reset_output_buffer(self) -> None:
        pass

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if self.fail_write:
            raise OSError(5, "Input/output error")
        return len(data)

    def flush(self) -> None:
        pass

    def read(self, size: int = 1) -> bytes:
        result = bytes(self.response[:size])
        del self.response[:size]
        return result

    def close(self) -> None:
        self.close_attempted = True
        if self.fail_close:
            raise RuntimeError("close failed")
        self.closed = True


class SerialFactory:
    def __init__(self, serials: list[RecoverySerial]) -> None:
        self.serials = list(serials)
        self.calls = 0

    def __call__(self, **_: object) -> RecoverySerial:
        self.calls += 1
        if not self.serials:
            raise AssertionError("serial factory called more often than expected")
        return self.serials.pop(0)


class ModbusRTURecoveryTests(unittest.TestCase):
    def test_eio_invalidates_cached_handle_and_next_read_reopens(self) -> None:
        response = append_crc(bytes.fromhex("6a03020104"))
        broken = RecoverySerial(fail_reset=True)
        recovered = RecoverySerial(response)
        factory = SerialFactory([broken, recovered])
        measurements = []
        client = ModbusRTUClient(
            "/dev/serial/by-id/test-rs485",
            timeout=0.01,
            retries=3,
            serial_factory=factory,
            request_observer=measurements.append,
        )

        with self.assertRaisesRegex(OSError, "Input/output error"):
            client.read_holding_register(106, 260)

        self.assertEqual(factory.calls, 1)
        self.assertEqual(broken.reset_calls, 1)
        self.assertTrue(broken.closed)
        self.assertEqual(broken.writes, [])
        self.assertEqual(measurements, [])

        self.assertEqual(client.read_holding_register(106, 260), 260)

        self.assertEqual(factory.calls, 2)
        self.assertEqual(len(recovered.writes), 1)
        self.assertEqual(len(measurements), 1)
        self.assertEqual(measurements[0].outcome, "success")

    def test_io_error_after_request_is_recorded_and_close_failure_does_not_mask_it(
        self,
    ) -> None:
        broken = RecoverySerial(fail_write=True, fail_close=True)
        factory = SerialFactory([broken])
        measurements = []
        client = ModbusRTUClient(
            "/dev/serial/by-id/test-rs485",
            timeout=0.01,
            retries=2,
            serial_factory=factory,
            request_observer=measurements.append,
        )

        with self.assertRaisesRegex(OSError, "Input/output error"):
            client.read_holding_register(106, 260)

        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(broken.writes), 1)
        self.assertTrue(broken.close_attempted)
        self.assertEqual(len(measurements), 1)
        self.assertEqual(measurements[0].outcome, "io_error")
        self.assertEqual(measurements[0].attempt, 1)


if __name__ == "__main__":
    unittest.main()
