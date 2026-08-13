"""Tests for the Phase 33 smart-glasses hub and tool."""

import pytest

from config import settings
from glasses.hub import GlassesHub, _best_glasses_candidate, glasses_prompt_block
from tools import build_default_registry
from tools.base import ToolError
from tools.glasses import GlassesTool


class FakeTTS:
    enabled = True
    spoken = []

    def speak(self, text):
        self.spoken.append(text)


@pytest.fixture
def hub(monkeypatch):
    h = GlassesHub(tts=FakeTTS())
    monkeypatch.setattr(h, "discover", lambda: ["Ray-Ban Wayfarer", "XREAL Air", "iPhone"])
    return h


def test_discover_returns_devices(hub):
    assert hub.discover() == ["Ray-Ban Wayfarer", "XREAL Air", "iPhone"]


def test_select_by_fragment(hub):
    result = hub.select("ray")
    assert "Ray-Ban" in result
    assert hub.active == "Ray-Ban Wayfarer"


def test_select_unknown_fragment_lists_known(hub):
    result = hub.select("nokia")
    assert "could not find" in result.lower()
    assert "Ray-Ban" in result


def test_select_prefers_glasses_like_device(monkeypatch):
    from glasses import hub as hubmod

    monkeypatch.setattr(hubmod, "_list_bluetooth_devices", lambda: ["iPhone", "XREAL Air", "Mouse"])
    assert _best_glasses_candidate() == "XREAL Air"


def test_notify_speaks_and_toasts(monkeypatch):
    from glasses import hub as hubmod

    toasts = []
    monkeypatch.setattr(hubmod, "_show_toast", lambda title, msg: toasts.append((title, msg)))
    h = GlassesHub(tts=FakeTTS())
    h._active = "Ray-Ban Wayfarer"
    result = h.notify("Hello from JARVIS")
    assert "Ray-Ban" in result
    assert toasts and toasts[0][1] == "Hello from JARVIS"
    assert h._tts.spoken == ["Hello from JARVIS"]


def test_notify_empty_is_clear(hub):
    assert "empty" in hub.notify("   ")


def test_notify_without_selection_is_honest(monkeypatch):
    from glasses import hub as hubmod

    monkeypatch.setattr(hubmod, "_show_toast", lambda t, m: None)
    h = GlassesHub(tts=FakeTTS())
    result = h.notify("hi")
    assert "no glasses are selected" in result.lower()


def test_status_shows_active_and_visible(hub):
    hub._active = "XREAL Air"
    status = hub.status()
    assert "XREAL Air" in status
    assert "3" in status


def test_tool_scan(monkeypatch):
    from tools import glasses as glasses_mod

    monkeypatch.setattr(settings, "glasses_enabled", True)
    monkeypatch.setattr(glasses_mod.GlassesHub, "discover", lambda self: ["Ray-Ban"])
    tool = GlassesTool()
    result = tool.execute({"action": "scan"})
    assert "Ray-Ban" in result


def test_tool_notify_requires_text(hub):
    from tools import glasses as glasses_mod

    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(settings, "glasses_enabled", True)
    tool = GlassesTool(hub=hub)
    with pytest.raises(ToolError, match="text"):
        tool.execute({"action": "notify"})
    monkeypatch.undo()


def test_tool_disabled_when_glasses_off(monkeypatch):
    monkeypatch.setattr(settings, "glasses_enabled", False)
    tool = GlassesTool(hub=GlassesHub())
    assert "disabled" in tool.execute({"action": "scan"})


def test_tool_unknown_action(hub):
    from tools import glasses as glasses_mod

    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(settings, "glasses_enabled", True)
    tool = GlassesTool(hub=hub)
    with pytest.raises(ToolError, match="action"):
        tool.execute({"action": "teleport"})
    monkeypatch.undo()


def test_prompt_block_is_honest():
    block = glasses_prompt_block()
    assert "glasses" in block
    assert "cannot embed" in block


def test_glasses_tool_registered():
    registry = build_default_registry()
    assert "glasses" in registry.names()