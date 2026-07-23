from __future__ import annotations

import unittest

from le01mp import LE01MPReader, REGISTER_BY_KEY, REGISTERS, decode_register


class FakeClient:
    def __init__(self, values: dict[tuple[int, int], int]) -> None:
        self.values = values
        self.calls: list[tuple[int, int]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.calls.append((unit_id, address))
        return self.values[(unit_id, address)]


class LE01MPTests(unittest.TestCase):
    def test_validated_register_map_excludes_unconfirmed_energy(self) -> None:
        self.assertEqual(
            [register.address for register in REGISTERS],
            [0, 1, 2, 3, 4, 5, 6, 37],
        )
        self.assertNotIn(7, [register.address for register in REGISTERS])

    def test_decodes_validated_scales(self) -> None:
        self.assertEqual(
            decode_register(201, REGISTER_BY_KEY["voltage"], 2301).value,
            230.1,
        )
        self.assertEqual(
            decode_register(201, REGISTER_BY_KEY["power_factor"], 955).value,
            0.955,
        )
        self.assertEqual(
            decode_register(201, REGISTER_BY_KEY["active_power"], 615).value,
            615.0,
        )

    def test_internal_temperature_uses_signed_int16(self) -> None:
        reading = decode_register(
            201,
            REGISTER_BY_KEY["internal_temperature"],
            0xFFFE,
        )
        self.assertEqual(reading.value, -2.0)

    def test_reader_requests_exactly_one_validated_register(self) -> None:
        client = FakeClient({(201, 0): 2301})
        reader = LE01MPReader(client)

        reading = reader.read_metric(201, "voltage")

        self.assertEqual(reading.value, 230.1)
        self.assertEqual(client.calls, [(201, 0)])

    def test_unknown_metric_is_rejected(self) -> None:
        reader = LE01MPReader(FakeClient({}))
        with self.assertRaisesRegex(ValueError, "Unknown LE-01MP"):
            reader.read_metric(201, "energy")


if __name__ == "__main__":
    unittest.main()
