"""
Focus-aware recap (Phase 30).

Watches for idle time on the machine (no keyboard/mouse activity for a
while) and fires an `on_idle` callback so JARVIS can gently nudge the user
back into focus with a short recap of what they were doing.

Idle time is measured via Windows `GetLastInputInfo` when available and
falls back to a simple "no user activity" heuristic elsewhere. A purely
additive daemon service: it never blocks and never crashes the app.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable

from utils.logger import get_logger

log = get_logger(__name__)

_GETLASTINPUTINFO = None
_IDLE_WRAPPER = None
_GETTICKCOUNT = None

try:  # pragma: no cover - Windows-only idle detection
    import ctypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    _GETLASTINPUTINFO = ctypes.windll.user32.GetLastInputInfo
    _IDLE_WRAPPER = _LASTINPUTINFO
    _GETTICKCOUNT = ctypes.windll.kernel32.GetTickCount
except Exception:  # pragma: no cover - not on Windows, or ctypes unavailable
    _GETLASTINPUTINFO = None


def idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input (best effort)."""
    if _GETLASTINPUTINFO is not None:
        try:
            info = _IDLE_WRAPPER()
            info.cbSize = ctypes.sizeof(_IDLE_WRAPPER)
            if _GETLASTINPUTINFO(ctypes.byref(info)):
                # dwTime is a GetTickCount (ms since boot); compare against
                # the same clock rather than epoch time.
                now = _GETTICKCOUNT() & 0xFFFFFFFF
                elapsed = (now - info.dwTime) & 0xFFFFFFFF
                return elapsed / 1000.0
        except Exception:  # noqa: BLE001
            pass
    return 0.0


class FocusRecapService:
    """Fires `on_idle` once after the machine has been idle long enough."""

    def __init__(
        self,
        idle_minutes: int = 15,
        on_idle: Callable[[], None] | None = None,
        poll_seconds: float = 30.0,
    ) -> None:
        self._idle_limit = float(idle_minutes) * 60.0
        self._on_idle = on_idle
        self._poll = float(poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._fired = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start the service. False if disabled or not on a supported OS."""
        if self.running:
            return True
        if self._idle_limit <= 0 or _GETLASTINPUTINFO is None:
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="focus-recap", daemon=True
        )
        self._thread.start()
        log.info(
            "Focus recap armed (idle threshold %s min)",
            int(self._idle_limit // 60),
        )
        return True

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check()
            except Exception as exc:  # noqa: BLE001
                log.debug("Focus recap check failed: %s", exc)
            self._stop.wait(self._poll)

    def _check(self) -> None:
        if idle_seconds() >= self._idle_limit:
            if not self._fired and self._on_idle is not None:
                self._fired = True
                log.info(
                    "User idle detected at %s - recap callback fired.",
                    datetime.now().strftime("%H:%M"),
                )
                self._on_idle()
        else:
            self._fired = False


_shared_service: FocusRecapService | None = None


def get_shared_service() -> FocusRecapService:
    """A FocusRecapService bound to the configured idle minutes."""
    global _shared_service
    if _shared_service is None:
        _shared_service = FocusRecapService(
            idle_minutes=settings.focus_recap_idle_minutes
        )
    return _shared_service