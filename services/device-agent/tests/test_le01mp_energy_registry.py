from __future__ import annotations

import unittest

from acquisition_registry import _le_target


class LE01MPEnergyRegistryTests(unittest.TestCase):
    def test_cumulative_energy_target_records_both_atomic_addresses(self) -> None:
        target = _le_target(201, "active_energy", "active")

        self.assertEqual(target.target_id, "le01mp:201-active-energy")
        self.assertEqual(target.telemetry_channel_id, "201-active-energy")
        self.assertEqual(target.metric, "electrical.energy.active")
        self.assertEqual(target.unit, "kWh")
        self.assertEqual(target.function, 3)
        self.assertEqual(target.addresses, (7, 8))

    def test_scalar_target_stays_single_register(self) -> None:
        target = _le_target(201, "voltage", "active")

        self.assertEqual(target.addresses, (0,))
        self.assertEqual(target.function, 3)


if __name__ == "__main__":
    unittest.main()
