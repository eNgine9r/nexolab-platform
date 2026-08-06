from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import CancelledError
from contextlib import contextmanager

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession


@contextmanager
def websocket_session(
    client: TestClient,
    path: str,
) -> Generator[WebSocketTestSession, None, None]:
    """Close a TestClient socket without leaking Starlette runner cancellation.

    Starlette's WebSocketTestSession exit stack sends the disconnect frame and then
    cancels its private runner task. Current Starlette versions can surface that
    expected runner cancellation as concurrent.futures.CancelledError after the
    application has already processed the close. Suppress only that framework
    teardown signal; application exceptions and lifecycle assertions remain visible.
    """

    session = client.websocket_connect(path)
    websocket = session.__enter__()
    try:
        yield websocket
    finally:
        try:
            session.__exit__(None, None, None)
        except CancelledError:
            pass
