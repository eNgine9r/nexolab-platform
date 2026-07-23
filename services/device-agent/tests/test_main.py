from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from main import Settings, parse_xjp60d_points


class SettingsTests(unittest.TestCase):
    def test_parses_and_deduplicates_xjp60d_points(self) -> None:
        self.assertEqual(
            parse_xjp60d_points("106:3, 106:4,106:3"),
            ((106, 3), (106, 4)),
        )

    def test_simulator_remains_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings.from_env()
        self.assertEqual(settings.device_mode, "simulator")
        self.assertEqual(settings.xjp60d_points, ())

    def test_hardware_mode_requires_points(self) -> None:
        with patch.dict(os.environ, {"DEVICE_MODE": "xjp60d"}, clear=True):
            with self.assertRaisesRegex(ValueError, "XJP60D_POINTS"):
                Settings.from_env()


if __name__ == "__main__":
    unittest.main()
