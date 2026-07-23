from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from main import Settings, parse_unit_ids, parse_xjp60d_points


class SettingsTests(unittest.TestCase):
    def test_parses_and_deduplicates_xjp60d_points(self) -> None:
        self.assertEqual(
            parse_xjp60d_points("106:3, 106:4,106:3"),
            ((106, 3), (106, 4)),
        )

    def test_parses_and_deduplicates_meter_unit_ids(self) -> None:
        self.assertEqual(
            parse_unit_ids("200, 201,200,203", label="LE-01MP"),
            (200, 201, 203),
        )

    def test_simulator_remains_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.device_mode, "simulator")
        self.assertEqual(settings.xjp60d_points, ())
        self.assertEqual(settings.le01mp_unit_ids, ())

    def test_xjp60d_mode_requires_points(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "xjp60d"}, clear=True):
            with self.assertRaisesRegex(ValueError, "XJP60D_POINTS"):
                Settings.from_env()

    def test_le01mp_mode_requires_units(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "le01mp"}, clear=True):
            with self.assertRaisesRegex(ValueError, "LE01MP_UNIT_IDS"):
                Settings.from_env()

    def test_combined_mode_accepts_both_sources(self) -> None:
        environment = {
            "DEVICE_MODE": "modbus",
            "XJP60D_POINTS": "106:3,106:4",
            "LE01MP_UNIT_IDS": "200,201,202,203",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = Settings.from_env()

        self.assertEqual(settings.device_mode, "modbus")
        self.assertEqual(settings.xjp60d_points, ((106, 3), (106, 4)))
        self.assertEqual(settings.le01mp_unit_ids, (200, 201, 202, 203))

    def test_combined_mode_requires_at_least_one_source(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "modbus"}, clear=True):
            with self.assertRaisesRegex(ValueError, "At least one"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
