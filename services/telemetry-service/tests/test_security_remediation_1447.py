"""Isolated remediation acceptance for verified 2026-10-30 image findings.

No vulnerability exception is granted by these tests; exact-head Trivy
policy must still pass independently.
"""
from __future__ import annotations

from io import BytesIO

import msgpack
from PIL import Image


def test_pillow_13_png_codec_round_trip() -> None:
    assert Image.__version__ == "13.0.0"
    source = Image.new("RGB", (2, 2), color=(1, 2, 3))
    output = BytesIO()
    source.save(output, format="PNG")
    output.seek(0)
    with Image.open(output) as restored:
        assert restored.size == (2, 2)
        assert restored.getpixel((0, 0)) == (1, 2, 3)


def test_msgpack_123_round_trip() -> None:
    assert msgpack.__version__ == "1.2.3"
    input_value = {"metric": "electrical.voltage", "value": 230.5}
    assert msgpack.unpackb(msgpack.packb(input_value)) == input_value
