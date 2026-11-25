"""Kernel clock synchronization status for honest sample timestamps (#1734 WP2e).

Reads the kernel NTP state with a read-only ``adjtimex`` call (``modes = 0``;
no privilege needed, never changes the clock). The kernel returns
``TIME_ERROR`` (5) while the clock is unsynchronized, which is the case after
a boot without a working RTC battery until a time source (NTP, local NTP or a
battery-backed RTC) disciplines it.

``ctypes`` is imported lazily: the minimal distroless runtime has no libffi,
and a missing optional probe must never stop acquisition. Without it the
fallback is systemd-timesyncd's marker ``/run/systemd/timesync/synchronized``
when the host directory is mounted read-only. Otherwise ``synchronized`` is
``None`` so callers never claim a synchronized clock without evidence.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

TIME_ERROR = 5
_TIMEX_BUFFER_BYTES = 512  # larger than struct timex on every Linux ABI; zeroed => modes = 0 (read-only)
_CACHE_SECONDS = 30.0
TIMESYNC_DIR = "/run/systemd/timesync"


def _default_adjtimex() -> Callable[[Any], int] | None:
    try:
        import ctypes
        import ctypes.util

        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        function = libc.adjtimex
    except (ImportError, OSError, AttributeError):
        return None
    function.argtypes = [ctypes.c_void_p]
    function.restype = ctypes.c_int
    return function


def _zeroed_buffer() -> Any:
    try:
        import ctypes
    except ImportError:
        return bytearray(_TIMEX_BUFFER_BYTES)
    return ctypes.create_string_buffer(_TIMEX_BUFFER_BYTES)


class ClockStatus:
    def __init__(
        self,
        adjtimex: Callable[[Any], int] | None | object = ...,
        monotonic: Callable[[], float] = time.monotonic,
        timesync_dir: str = TIMESYNC_DIR,
    ) -> None:
        self._adjtimex = _default_adjtimex() if adjtimex is ... else adjtimex
        self._monotonic = monotonic
        self._timesync_dir = timesync_dir
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
        if self._adjtimex is not None:
            try:
                state = int(self._adjtimex(_zeroed_buffer()))
            except Exception:  # noqa: BLE001 - seccomp or ABI failure must not break health
                state = -1
            if state >= 0:
                return {"synchronized": state != TIME_ERROR, "kernel_state": state, "source": "adjtimex"}
        # Fallback only when the host timesync directory is actually mounted:
        # an absent directory means "unknown", never "unsynchronized".
        if os.path.isdir(self._timesync_dir):
            synced = os.path.exists(os.path.join(self._timesync_dir, "synchronized"))
            return {"synchronized": synced, "kernel_state": None, "source": "timesyncd-marker"}
        return {"synchronized": None, "kernel_state": None, "source": "unavailable"}


_DEFAULT: ClockStatus | None = None
_DEFAULT_LOCK = threading.Lock()


def clock_status() -> dict[str, Any]:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = ClockStatus()
    try:
        return _DEFAULT.snapshot()
    except Exception:  # noqa: BLE001 - health must never fail because of this probe
        return {"synchronized": None, "kernel_state": None, "source": "unavailable"}
