from __future__ import annotations

from io import BytesIO

import pytest

from app.http_transport import (
    MAX_HTTP_RESPONSE_BYTES,
    HttpTransportError,
    _bounded_read,
)


def test_bounded_read_accepts_response_at_limit() -> None:
    payload = b"x" * MAX_HTTP_RESPONSE_BYTES
    assert _bounded_read(BytesIO(payload)) == payload


def test_bounded_read_rejects_oversized_response() -> None:
    payload = b"x" * (MAX_HTTP_RESPONSE_BYTES + 1)
    with pytest.raises(HttpTransportError, match="bounded size"):
        _bounded_read(BytesIO(payload))
