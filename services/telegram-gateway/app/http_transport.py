from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import socket

MAX_HTTP_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str]


class HttpTransportError(RuntimeError):
    pass


class HttpTransport(Protocol):
    def __call__(self, request: Request, timeout_seconds: float) -> HttpResponse: ...


def urlopen_transport(request: Request, timeout_seconds: float) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - bounded configured endpoints
            return HttpResponse(
                status=int(response.status),
                body=_bounded_read(response),
                headers=dict(response.headers.items()),
            )
    except HTTPError as error:
        return HttpResponse(
            status=int(error.code),
            body=_bounded_read(error),
            headers=dict(error.headers.items()) if error.headers is not None else {},
        )
    except (URLError, TimeoutError, socket.timeout, OSError) as error:
        raise HttpTransportError("HTTP transport failed") from error


def _bounded_read(stream) -> bytes:
    body = stream.read(MAX_HTTP_RESPONSE_BYTES + 1)
    if len(body) > MAX_HTTP_RESPONSE_BYTES:
        raise HttpTransportError("HTTP response exceeded bounded size")
    return body
