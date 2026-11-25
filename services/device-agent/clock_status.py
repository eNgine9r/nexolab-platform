"""Kernel clock synchronization status for honest sample timestamps (#1734 WP2e).

Reads the kernel NTP state with a read-only ``adjtimex`` call (``modes = 0``;
no privilege needed, never changes the clock). The kernel returns
``TIME_ERROR`` (5) while the clock is unsynchronized, which is the case after
a boot without a working RTC battery until a time source (NTP, local NTP or a
battery-backed RTC) disciplines it. ``synchronized`` is ``None`` when the
call is unavailable (non-Linux, seccomp, no ctypes) so callers never claim a
synchronized clock without evidence.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import threading
import time
from collections.abc import Callable
from typing import Any

TIME_ERROR = 5
_TIMEX_BUFFER_BYTES = 512  # larger than struct timex on every Linux ABI; zeroed => modes = 0 (read-only)
_CACHE_SECONDS = 30.0


def _default_adjtimex() -> Callable[[ctypes.Array], int] | None:
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        function = libc.adjtimex
    except (OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_void_p]
    function.restype = ctypes.c_int
    return function


class ClockStatus:
    def __init__(
        self,
        adjtimex: Callable[[ctypes.Array], int] | None | object = ...,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adjtimex = _default_adjtimex() if adjtimex is ... else adjtimex
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cached: tuple[float, dict[str, Any]] | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = self._monotonic()
            if self._cached and now - self._cached[0] < _CACHE_SECONDS:
                return dict(self._cached[1])
            result = self._read()
            self._cached = (now, result)
            return dict(result)

    def _read(self) -> dict[str, Any]:
        if self._adjtimex is None:
            return {"synchronized": None, "kernel_state": None, "source": "unavailable"}
        buffer = ctypes.create_string_buffer(_TIMEX_BUFFER_BYTES)
        try:
            state = int(self._adjtimex(buffer))
        except Exception:  # noqa: BLE001 - seccomp or ABI failure must not break health
            return {"synchronized": None, "kernel_state": None, "source": "unavailable"}
        if state < 0:
            return {"synchronized": None, "kernel_state": state, "source": "unavailable"}
        return {"synchronized": state != TIME_ERROR, "kernel_state": state, "source": "adjtimex"}


_DEFAULT = ClockStatus()


def clock_status() -> dict[str, Any]:
    return _DEFAULT.snapshot()
