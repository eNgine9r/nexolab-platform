from __future__ import annotations

import re
from pathlib import Path

from main import parse_unit_ids, parse_xjp60d_points


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HARDWARE_COMPOSE = REPOSITORY_ROOT / "infrastructure" / "compose" / "compose.hardware.yaml"


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
        r"XJP60D_DISCOVERY_UNITS:\s*\$\{XJP60D_DISCOVERY_UNITS:-(?P<units>[^}]+)\}",
        content,
    )
    assert match is not None

    units = parse_unit_ids(match.group("units"), label="XJP60D discovery")
    expected = (*range(101, 115), *range(126, 139))

    assert units == expected
    assert len(units) == 27
    assert 106 in units
    assert 126 in units  # KK1 sensor inventory number 200 maps to 126-04.
