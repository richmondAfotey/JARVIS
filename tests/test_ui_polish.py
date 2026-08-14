"""Tests for Phase 17 UI/UX polish components (constructed without a page)."""

import threading
import time

from ui.chat_view import ChatView
from ui.components.orb import Orb
from ui.components.status_indicator import StatusIndicator


def test_orb_default_mode_and_switch():
    orb = Orb(size=80)
    assert orb.current_mode() == "idle"
    orb.set_mode("thinking")
    assert orb.current_mode() == "thinking"
    orb.set_mode("speaking")
    orb.set_mode("listening")
    assert orb.current_mode() == "listening"


def test_orb_ignores_unknown_mode():
    orb = Orb(size=80)
    orb.set_mode("warp-speed")
    assert orb.current_mode() == "idle"


def test_orb_starts_and_stops():
    orb = Orb(size=80)
    orb.start()
    try:
        time.sleep(0.2)
    finally:
        orb.stop()
    assert orb.current_mode() == "idle"


def test_status_indicator_fallback():
    indicator = StatusIndicator("idle")
    indicator.set_state("thinking")
    assert indicator._state == "thinking"
    indicator.set_state("not-a-real-state")
    assert indicator._state == "idle"


def test_status_indicator_known_states():
    indicator = StatusIndicator()
    for state in ("idle", "listening", "thinking", "speaking", "executing", "error"):
        indicator.set_state(state)
        assert indicator._state == state


def test_chat_view_thinking_bubble_removable():
    chat = ChatView(assistant_name="JARVIS")
    thinking = chat.thinking()
    time.sleep(0.4)  # let the animation thread tick a few times
    thinking.remove()
    chat.clear()
    assert True  # no exceptions constructing/removing off-page


def test_chat_view_streaming_bubble():
    chat = ChatView(assistant_name="JARVIS")
    bubble = chat.begin_message("assistant")
    bubble.append("hello ")
    bubble.append("world")
    bubble.start_caret()
    time.sleep(0.5)
    bubble.finish()
    assert bubble._base == "hello world"
    chat.clear()


# -- Phase 22 fix: reply speaking must never block the chat flow -----------

class _FakeStatus:
    def __init__(self):
        self._state = "idle"

    def set_state(self, state):
        self._state = state


class _FakeOrb:
    def __init__(self):
        self.mode = "idle"

    def set_mode(self, mode):
        self.mode = mode


class _FakeWake:
    def __init__(self):
        self.running = False

    def pause(self):
        pass

    def resume(self):
        pass


class _FakePage:
    def update(self):
        pass


class _FakeTTSSlow:
    """Simulates a speech engine that takes a while (never truly hangs,
    but long enough to prove _start_reply_speaking does not wait)."""
    def __init__(self, **kwargs):
        self.started = False
        self.enabled = kwargs.pop("enabled", True)
        self.rate = 180
        self.voice_name = ""

    def set_rate(self, value):
        self.rate = value

    def set_voice(self, value):
        self.voice_name = value

    def set_enabled(self, value):
        self.enabled = value

    def list_voices(self):
        return ["Test Voice"]

    def speak(self, text, emotion=None):
        self.started = True
        time.sleep(0.4)


def _make_dashboard(**tts_kwargs):
    from ui.dashboard import Dashboard

    dash = object.__new__(Dashboard)
    dash.status = _FakeStatus()
    dash.orb = _FakeOrb()
    dash.wake_listener = _FakeWake()
    dash.tts = _FakeTTSSlow(**tts_kwargs)
    dash.busy = False
    dash._page = _FakePage()
    dash._speaking_seq = 0
    _attach_dashboard_voice_state(dash)
    return dash


def _attach_dashboard_voice_state(dash, continuous=False):
    """Phase 36/37 wiring the Dashboard now expects on its attributes."""
    dash.continuous_enabled = continuous
    dash._continuous_session = False
    dash._speech_finished = threading.Event()
    dash._speech_pending = False
    dash.continuous_button = type(
        "CB",
        (),
        {
            "update": lambda self: None,
            "icon": None,
            "icon_color": None,
            "tooltip": None,
        },
    )()
    dash.bedtime = type(
        "BT",
        (),
        {"active": False, "set_active": lambda self, _active: None},
    )()


def test_reply_speaking_returns_immediately_not_blocking():
    dash = _make_dashboard()
    # Pre-set the states a real reply flow would have reached: the reply has
    # finished rendering and speaking is about to start.
    started = time.monotonic()
    dash._start_reply_speaking("hello world")
    elapsed = time.monotonic() - started
    # Returns well before the (slow) fake audio finishes -> not blocking.
    assert elapsed < 0.3
    # status stays exactly as the caller left it (idle) - no stuck state.
    assert dash.status._state == "idle"


def test_reply_speaking_restores_idle_after_audio():
    dash = _make_dashboard()
    dash._start_reply_speaking("hello world")
    time.sleep(1.0)  # wait for the daemon speaker thread to finish
    # The speaker thread resets to idle once audio completes.
    assert dash.status._state == "idle"
    assert dash.orb.mode == "idle"


# -- Phase 32: settings must surface the camera toggle ----------------------

def test_settings_dialog_has_camera_toggle():
    from ui.settings_view import SettingsView

    view = SettingsView(None, on_save=lambda v: None)
    assert hasattr(view, "camera_enabled")
    assert view.camera_enabled.value is True  # default: always-on camera


def test_settings_save_persists_camera_preference(monkeypatch):
    from ui.dashboard import Dashboard
    from ui.settings_view import SettingsView

    dash = object.__new__(Dashboard)
    dash.busy = False
    dash.tts = _FakeTTSSlow()
    dash.wake_listener = _FakeWake()
    dash.brain = type("B", (), {"unrestricted_mode": False})()
    prefs = {}

    class _FakeDB:
        def set_preference(self, key, value):
            prefs[key] = value

    class _FakeCamera:
        running = False

        def stop(self):
            pass

    dash.database = _FakeDB()
    dash.camera_monitor = _FakeCamera()
    dash._page = _FakePage()
    dash.chat = ChatView(assistant_name="JARVIS")
    dash.speaker_button = type(
        "S", (), {"update": lambda self: None}
    )()
    _attach_dashboard_voice_state(dash)
    calls = {"camera": None}

    def fake_set_camera(running):
        calls["camera"] = running

    dash._set_camera_monitor_running = fake_set_camera
    dash._set_unrestricted = lambda _enabled: None
    dash._set_wake_running = lambda _enabled: None

    view = SettingsView(None, on_save=lambda v: None)
    view.camera_enabled.value = False
    dash._on_settings_save(view)

    assert prefs.get("camera_fall_enabled") == "false"
    assert calls["camera"] is False


def test_settings_save_persists_camera_enabled():
    from ui.dashboard import Dashboard
    from ui.settings_view import SettingsView

    dash = object.__new__(Dashboard)
    dash.busy = False
    dash.tts = _FakeTTSSlow()
    dash.wake_listener = _FakeWake()
    dash.brain = type("B", (), {"unrestricted_mode": False})()
    prefs = {}

    class _FakeDB:
        def set_preference(self, key, value):
            prefs[key] = value

    class _FakeCamera:
        running = False

        def stop(self):
            pass

    dash.database = _FakeDB()
    dash.camera_monitor = _FakeCamera()
    dash._page = _FakePage()
    dash.chat = ChatView(assistant_name="JARVIS")
    dash.speaker_button = type(
        "S", (), {"update": lambda self: None}
    )()
    _attach_dashboard_voice_state(dash)
    dash._set_camera_monitor_running = lambda running: None
    dash._set_unrestricted = lambda _enabled: None
    dash._set_wake_running = lambda _enabled: None

    view = SettingsView(None, on_save=lambda v: None)
    view.camera_enabled.value = True
    dash._on_settings_save(view)

    assert prefs.get("camera_fall_enabled") == "true"