from __future__ import annotations

import re
import unittest
from pathlib import Path

from main import parse_unit_ids, parse_xjp60d_points


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HARDWARE_COMPOSE = REPOSITORY_ROOT / "infrastructure" / "compose" / "compose.hardware.yaml"
WAVESHARE_PROFILE = REPOSITORY_ROOT / "config" / "edge" / "waveshare-8ai-v3-readonly-profile.yaml"


def test_hardware_compose_keeps_continuous_polling_bounded() -> None:
    content = HARDWARE_COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        r"XJP60D_POINTS:\s*\$\{XJP60D_POINTS:-(?P<points>[^}]+)\}",
        content,
    )
    assert match is not None

    points = parse_xjp60d_points(match.group("points"))

    assert points == ((106, 3), (106, 4))
    assert len(points) == 2


def test_hardware_compose_keeps_full_catalog_for_on_demand_discovery_only() -> None:
    content = HARDWARE_COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        r"XJP60D_DISCOVERY_UNITS:\s*[\"']?\$\{XJP60D_DISCOVERY_UNITS:-(?P<units>[^}]+)\}",
        content,
    )
    assert match is not None

    units = parse_unit_ids(match.group("units"), label="XJP60D discovery")
    expected = (*range(96, 115), *range(126, 139))

    assert units == expected
    assert len(units) == 32
    assert 96 in units
    assert 106 in units
    assert 115 not in units
    assert 126 in units  # KK1 sensor inventory number 200 maps to 126-04.


class HardwareComposeSDM120ContractTests(unittest.TestCase):
    def test_sdm120_polling_is_explicit_and_disabled_by_default(self) -> None:
        content = HARDWARE_COMPOSE.read_text(encoding="utf-8")

        self.assertIn('SDM120_UNIT_IDS: "${SDM120_UNIT_IDS:-}"', content)
        self.assertIn('SDM120_BUS_ID: "${SDM120_BUS_ID:-}"', content)
        self.assertNotIn("SDM120_UNIT_IDS: 1", content)


class HardwareComposeWaveshareContractTests(unittest.TestCase):
    def test_waveshare_polling_is_explicit_and_disabled_by_default(self) -> None:
        content = HARDWARE_COMPOSE.read_text(encoding="utf-8")

        self.assertIn('WAVESHARE_8AI_UNIT_IDS: "${WAVESHARE_8AI_UNIT_IDS:-}"', content)
        self.assertIn('WAVESHARE_8AI_BUS_ID: "${WAVESHARE_8AI_BUS_ID:-}"', content)
        self.assertNotIn("WAVESHARE_8AI_UNIT_IDS: 1", content)

    def test_waveshare_candidate_profile_pins_verified_read_only_identity(self) -> None:
        content = WAVESHARE_PROFILE.read_text(encoding="utf-8")

        self.assertIn("bus_id: rs485-waveshare", content)
        self.assertIn("A10Q2QYX-if00-port0", content)
        self.assertIn("unit_id: 1", content)
        self.assertIn("allowed_functions: [3, 4]", content)
        self.assertIn("prohibited_functions: [5, 6, 15, 16]", content)
        self.assertIn("required_mode_for_acceptance: 3", content)
        self.assertIn("raw_unit: uA", content)
        self.assertIn("raw_min: 4000", content)
        self.assertIn("raw_max: 20000", content)
        self.assertIn("physical_channel: unresolved", content)
        self.assertIn("engineering_range: unresolved", content)


class HardwareComposeEmbracoContractTests(unittest.TestCase):
    def test_passes_only_explicit_embraco_enrollment(self) -> None:
        content = HARDWARE_COMPOSE.read_text(encoding="utf-8")

        self.assertIn('EMBRACO_UNIT_IDS: "${EMBRACO_UNIT_IDS:-}"', content)
        self.assertNotIn("EMBRACO_TEMPERATURE_SCALE:", content)
        self.assertNotIn("EMBRACO_CONTROL_SCALE:", content)


def test_hardware_compose_keeps_nonroot_serial_group_boundary_minimal() -> None:
    content = HARDWARE_COMPOSE.read_text(encoding="utf-8")

    assert '"${RS485_GROUP_GID:-20}"' in content
    assert '"${RS485_COMMISSIONING_GROUP_GID:-46}"' in content
    assert '"c 188:* rwm"' in content
    assert "privileged: true" not in content
