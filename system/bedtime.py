"""
Bedtime mode (Phase 37): quiet hours + gentle screen dimming.

Two pieces:

1. `in_bedtime_hours()` - pure schedule check. Supports overnight windows
   ("22:30" -> "06:30") and refuses to guess on malformed times.

2. `BedtimeMonitor` - a tiny daemon thread that enforces the quiet-hours
   schedule from Settings. While active, the dashboard suppresses spoken
   replies and glasses mirroring (text-only, silent). The screen is dimmed
   via the Windows monitor-brightness API when available; the original
   brightness is restored when bedtime ends. Every hardware call is
   best-effort and never blocks the app.

Design notes:
    * The monitor is OFF by default (no schedule). When no schedule is
      configured, manual on/off via the `bedtime_mode` tool or the Settings
      toggle is left alone - the monitor never overrides the user.
    * Screen dimming is a "nice to have": on hardware/drivers without the
      brightness API, JARVIS still goes quiet and simply skips the dim.
"""

from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from datetime import datetime

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

#: Where the screen is dimmed to during bedtime mode (0-100).
_BEDTIME_BRIGHTNESS = 30


def in_bedtime_hours(
    now: datetime, start: str, end: str
) -> bool:
    """True when `now` falls inside the quiet window (HH:MM strings).

    Handles overnight ranges (start > end) and returns False for empty or
    malformed times so a typo never locks the screen dimmed.
    """
    if not start or not end:
        return False

    def to_minutes(value: str) -> int:
        try:
            hours, minutes = value.strip().split(":", 1)
            return int(hours) * 60 + int(minutes)
        except (ValueError, AttributeError):
            return -1

    current = now.hour * 60 + now.minute
    s, e = to_minutes(start), to_minutes(end)
    if s < 0 or e < 0:
        return False
    if s == e:
        return False  # zero-length window: never active
    if s < e:
        return s <= current < e
    # Overnight window (e.g. 22:30 -> 06:30).
    return current >= s or current < e


# -- Monitor brightness (Windows, best-effort) ------------------------------

def _first_physical_monitor_brightness() -> int | None:
    """Current brightness of the first physical monitor, or None."""
    if os.name != "nt":
        return None
    try:
        monitors = _physical_monitors()
        if not monitors:
            return None
        dxva2 = ctypes.windll.dxva2
        level = wintypes.DWORD()
        if dxva2.GetMonitorBrightness(monitors[0], ctypes.byref(level), ctypes.byref(level), ctypes.byref(level)):
            return int(level.value)
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not read monitor brightness: %s", exc)
    return None


def _physical_monitors() -> list:
    """Handles for every physical monitor attached to the primary display."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    dxva2 = ctypes.windll.dxva2
    found: list = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _enum(hmon, _hdc, _rect, _data):
        found.append(hmon)
        return True

    user32.EnumDisplayMonitors(
        None, None, MONITORENUMPROC(_enum), 0
    )

    handles: list = []
    for hmon in found:
        try:
            count = wintypes.DWORD()
            if not dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(hmon, ctypes.byref(count)):
                continue
            if not count.value:
                continue
            pm_count = int(count.value)
            PhysicalMonitor = ctypes.Structure()
            PhysicalMonitor._fields_ = [
                ("hPhysicalMonitor", wintypes.HANDLE),
                ("szPhysicalMonitorDescription", ctypes.c_wchar * 128),
            ]
            arr = (PhysicalMonitor * pm_count)()
            if dxva2.GetPhysicalMonitorsFromHMONITOR(hmon, pm_count, arr):
                for i in range(pm_count):
                    handles.append(arr[i].hPhysicalMonitor)
        except Exception:  # noqa: BLE001 - driver quirks must not break us
            continue
    return handles


def set_screen_brightness(level: int) -> bool:
    """Set the brightness of every attached monitor (best-effort).

    Returns True if at least one monitor accepted the change. On systems
    without the brightness API this simply reports False (no crash).
    """
    if os.name != "nt":
        return False
    level = max(0, min(100, int(level)))
    try:
        dxva2 = ctypes.windll.dxva2
        changed = False
        for handle in _physical_monitors():
            try:
                if dxva2.SetMonitorBrightness(handle, level):
                    changed = True
            except Exception:  # noqa: BLE001
                continue
            finally:
                try:
                    dxva2.DestroyPhysicalMonitor(handle)
                except Exception:  # noqa: BLE001
                    pass
        return changed
    except Exception as exc:  # noqa: BLE001
        log.debug("Brightness control unavailable: %s", exc)
        return False


class BedtimeMonitor:
    """Enforces the quiet-hours schedule on a daemon thread (Phase 37)."""

    def __init__(self, cfg=settings, on_change=None):
        self.cfg = cfg
        #: Optional callback(active: bool) fired when bedtime starts/ends.
        self.on_change = on_change or (lambda active: None)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False
        self._saved_brightness: int | None = None

    # -- State --------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self._active

    # -- Lifecycle ----------------------------------------------------------
    def start(self) -> None:
        """Start the scheduler thread (safe to call more than once)."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="bedtime-monitor"
        )
        self._thread.start()
        # Apply the schedule immediately so a quiet window that started
        # before launch is honoured right away.
        self.tick()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(30):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 - never kill the thread
                log.debug("Bedtime tick failed: %s", exc)

    # -- Actions ------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        if active:
            self.activate()
        else:
            self.deactivate()

    def activate(self, dim: bool = True) -> None:
        with self._lock:
            if self._active:
                return
            self._active = True
            if dim:
                if self._saved_brightness is None:
                    self._saved_brightness = _first_physical_monitor_brightness()
                set_screen_brightness(_BEDTIME_BRIGHTNESS)
            self.on_change(True)
            log.info("Bedtime mode ON")

    def deactivate(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            if self._saved_brightness is not None:
                set_screen_brightness(self._saved_brightness)
                self._saved_brightness = None
            self.on_change(False)
            log.info("Bedtime mode OFF")

    def tick(self) -> None:
        """Re-evaluate the quiet-hours schedule (called every ~30s)."""
        cfg = self.cfg
        schedule_on = bool(getattr(cfg, "bedtime_schedule_enabled", False))
        if not schedule_on:
            # No schedule: the monitor never overrides a manual on/off.
            return
        in_window = in_bedtime_hours(
            datetime.now(), cfg.bedtime_start, cfg.bedtime_end
        )
        if in_window:
            self.activate()
        else:
            self.deactivate()


# -- Shared instance (mirrors the ptt.get_shared_ptt pattern) ---------------

_shared: BedtimeMonitor | None = None
_shared_lock = threading.Lock()


def get_bedtime_monitor(on_change=None) -> BedtimeMonitor:
    """Return the process-wide bedtime monitor."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = BedtimeMonitor(on_change=on_change)
        return _shared
