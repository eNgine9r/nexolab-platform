from __future__ import annotations

import unittest

from le01mp import (
    LE01MPReader,
    REGISTER_BY_KEY,
    REGISTERS,
    decode_register,
    decode_registers,
)


class FakeClient:
    def __init__(
        self,
        values: dict[tuple[int, int], int] | None = None,
        ranges: dict[tuple[int, int, int], tuple[int, ...]] | None = None,
    ) -> None:
        self.values = values or {}
        self.ranges = ranges or {}
        self.calls: list[tuple[object, ...]] = []

    def read_holding_register(self, unit_id: int, address: int) -> int:
        self.calls.append(("single", unit_id, address))
        return self.values[(unit_id, address)]

    def read_holding_registers(
        self,
        unit_id: int,
        address: int,
        count: int,
    ) -> tuple[int, ...]:
        self.calls.append(("range", unit_id, address, count))
        return self.ranges[(unit_id, address, count)]


class LE01MPTests(unittest.TestCase):
    def test_validated_register_map_includes_atomic_cumulative_energy(self) -> None:
        self.assertEqual(
            [register.address for register in REGISTERS],
            [0, 1, 2, 3, 4, 5, 6, 7, 37],
        )
        energy = REGISTER_BY_KEY["active_energy"]
        self.assertEqual(energy.addresses, (7, 8))
        self.assertEqual(energy.count, 2)
        self.assertEqual(energy.metric, "electrical.energy.active")
        self.assertEqual(energy.unit, "kWh")
        self.assertEqual(energy.scale, 0.01)

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

    def test_recorded_hardware_frames_decode_cumulative_energy(self) -> None:
        samples = {
            200: ((20, 63791), 1374511, 13745.11),
            201: ((38, 49806), 2540174, 25401.74),
            202: ((17, 15498), 1129610, 11296.10),
            203: ((21, 2364), 1378620, 13786.20),
        }

        for unit_id, (words, expected_raw, expected_kwh) in samples.items():
            with self.subTest(unit_id=unit_id):
                reading = decode_registers(
                    unit_id,
                    REGISTER_BY_KEY["active_energy"],
                    words,
                )
                self.assertEqual(reading.raw_value, expected_raw)
                self.assertEqual(reading.value, expected_kwh)
                self.assertEqual(reading.unit, "kWh")
                self.assertEqual(reading.metric, "electrical.energy.active")

    def test_reader_requests_one_scalar_register_for_existing_metrics(self) -> None:
        client = FakeClient(values={(201, 0): 2301})
        reader = LE01MPReader(client)

        reading = reader.read_metric(201, "voltage")

        self.assertEqual(reading.value, 230.1)
        self.assertEqual(client.calls, [("single", 201, 0)])

    def test_reader_requests_energy_words_atomically(self) -> None:
        client = FakeClient(ranges={(201, 7, 2): (38, 49806)})
        reader = LE01MPReader(client)

        reading = reader.read_metric(201, "active_energy")

        self.assertEqual(reading.raw_value, 2540174)
        self.assertEqual(reading.value, 25401.74)
        self.assertEqual(client.calls, [("range", 201, 7, 2)])

    def test_multi_register_metric_rejects_scalar_decoder(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires 2 register words"):
            decode_register(201, REGISTER_BY_KEY["active_energy"], 38)

    def test_wrong_energy_word_count_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "expects 2 register word"):
            decode_registers(
                201,
                REGISTER_BY_KEY["active_energy"],
                (38,),
            )

    def test_unknown_metric_is_rejected(self) -> None:
        reader = LE01MPReader(FakeClient())
        with self.assertRaisesRegex(ValueError, "Unknown LE-01MP"):
            reader.read_metric(201, "energy")


if __name__ == "__main__":
    unittest.main()
