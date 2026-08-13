"""
Push-to-talk hotkey service (Phase 30).

Registers a global hotkey (default ``ctrl+space``) that triggers a
mic-recording session - a walkie-talkie style shortcut so the user doesn't
have to click the mic button. Pressing the hotkey fires an ``on_trigger``
callback; the dashboard runs its existing (tested) mic flow from there, and
the STT phrase-completion naturally ends the recording.

Uses the optional third-party `keyboard` library for global hotkeys. When
that is not installed the service reports itself unavailable and the app
silently falls back to the normal mic button. Everything is lazy and
defensive so the app still starts without the library.
"""

from __future__ import annotations

import threading
from typing import Callable

from utils.logger import get_logger

log = get_logger(__name__)

_kb = None  # lazy import of the 'keyboard' library
_hotkey_available: bool | None = None


def _init_kb():
    """Import the keyboard library once, caching availability."""
    global _kb, _hotkey_available
    if _hotkey_available is not None:
        return _kb
    try:
        import keyboard  # noqa: PLC0415
        _kb = keyboard
        _hotkey_available = True
    except Exception:  # noqa: BLE001
        _kb = None
        _hotkey_available = False
    return _kb


def hotkey_available() -> bool:
    return _init_kb() is not None


class PushToTalk:
    """Fires `on_trigger` whenever the global hotkey is pressed."""

    def __init__(
        self,
        hotkey: str = "ctrl+space",
        on_trigger: Callable[[], None] | None = None,
    ):
        self.hotkey = hotkey
        self.on_trigger = on_trigger
        self._lock = threading.Lock()
        self._armed = False

    @property
    def available(self) -> bool:
        return hotkey_available()

    @property
    def armed(self) -> bool:
        return self._armed

    def start(self) -> bool:
        """Register the hotkey. Returns False when the lib is missing."""
        if not self.available:
            log.info("Push-to-talk unavailable (no 'keyboard' library).")
            return False
        with self._lock:
            if self._armed:
                return True
            try:
                _init_kb().add_hotkey(self.hotkey, self._trigger, suppress=False)
                self._armed = True
                log.info("Push-to-talk armed on %s", self.hotkey)
                return True
            except Exception as exc:  # noqa: BLE001
                log.error("PTT hotkey registration failed: %s", exc)
                return False

    def stop(self) -> None:
        """Unhook the hotkey (best effort)."""
        with self._lock:
            if self._armed:
                try:
                    _init_kb().remove_hotkey(self.hotkey)
                except Exception:  # noqa: BLE001
                    pass
                self._armed = False

    def _trigger(self) -> None:
        log.info("PTT hotkey pressed.")
        if self.on_trigger is not None:
            self.on_trigger()


_shared_ptt: PushToTalk | None = None
_shared_ptt_lock = threading.Lock()


def get_shared_ptt(on_trigger: Callable[[], None] | None = None) -> PushToTalk:
    """A process-wide PushToTalk bound to the configured hotkey."""
    global _shared_ptt
    with _shared_ptt_lock:
        if _shared_ptt is None:
            from config import settings

            _shared_ptt = PushToTalk(
                hotkey=settings.ptt_hotkey,
                on_trigger=on_trigger,
            )
        elif on_trigger is not None:
            _shared_ptt.on_trigger = on_trigger
        return _shared_ptt