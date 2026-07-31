from __future__ import annotations

import re
from pathlib import Path

from main import parse_xjp60d_points


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
HARDWARE_COMPOSE = REPOSITORY_ROOT / "infrastructure" / "compose" / "compose.hardware.yaml"


def test_hardware_compose_polls_every_catalogued_dixell_input() -> None:
    content = HARDWARE_COMPOSE.read_text(encoding="utf-8")
    match = re.search(
        r"XJP60D_POINTS:\s*\$\{XJP60D_POLL_POINTS:-(?P<points>[^}]+)\}",
        content,
    )
    assert match is not None

    points = parse_xjp60d_points(match.group("points"))
    expected = tuple(
        (unit_id, channel)
        for unit_id in (*range(101, 115), *range(126, 139))
        for channel in range(1, 7)
    )

    assert points == expected
    assert len(points) == 162
    assert (106, 3) in points
    assert (106, 4) in points
    assert (126, 4) in points  # KK1 physical sensor inventory number 200.
