"""Tests for Phase 37: Einstein, lighting, printing, bedtime mode.

No internet, no printer, and no monitor-brightness hardware needed - every
external call is faked.
"""

from datetime import datetime

import pytest

from tools.builtin import register_defaults
from tools.registry import ToolRegistry
from tools.einstein import EINSTEIN_FACTS, EINSTEIN_QUOTES, EinsteinTool
from tools.lighting import LIGHTING_RECIPES, LightingTool
from tools.printing import PRINTABLE_EXTENSIONS, PrintTool
from tools.bedtime import BedtimeTool

import system.bedtime as bedtime_mod
from system.bedtime import BedtimeMonitor, in_bedtime_hours


# -- Einstein ---------------------------------------------------------------

def test_einstein_quote():
    result = EinsteinTool().execute({})
    assert '"' in result and "Albert Einstein" in result


def test_einstein_fact():
    result = EinsteinTool().execute({"kind": "fact"})
    assert result.startswith("Did you know?")
    assert "Albert Einstein" in result


def test_einstein_daily_is_stable_and_rotates():
    t = EinsteinTool()
    today = t.execute({"kind": "daily"})
    assert today == t.execute({"kind": "daily"})
    assert any(q in today for q in EINSTEIN_QUOTES)


def test_einstein_bad_kind_raises():
    with pytest.raises(Exception):
        EinsteinTool().execute({"kind": "horoscope"})


# -- Lighting ---------------------------------------------------------------

def test_lighting_lists_moods_when_none_given():
    result = LightingTool().execute({})
    for mood in ("focus", "reading", "relax", "movie", "bedtime", "energy"):
        assert mood in result


def test_lighting_recipe_contains_kelvin_and_brightness():
    result = LightingTool().execute({"mood": "focus"})
    assert "5000K" in result
    assert "100% brightness" in result
    assert "Albert" not in result


def test_lighting_unknown_mood_raises():
    with pytest.raises(Exception):
        LightingTool().execute({"mood": "disco"})


def test_lighting_recipes_have_required_keys():
    for recipe in LIGHTING_RECIPES.values():
        assert "kelvin" in recipe and "brightness" in recipe and "hint" in recipe


# -- Printing ---------------------------------------------------------------

def test_print_requires_path():
    with pytest.raises(Exception):
        PrintTool().execute({})


def test_print_missing_file_raises():
    with pytest.raises(Exception):
        PrintTool().execute({"path": "Z:/definitely/not/here.txt"})


def test_print_rejects_unsupported_extension(tmp_path):
    target = tmp_path / "report.exe"
    target.write_bytes(b"MZ")
    with pytest.raises(Exception):
        PrintTool().execute({"path": str(target)})


def test_print_sends_to_default_printer(tmp_path, monkeypatch):
    sent = {}

    def fake_startfile(path, operation):
        sent["path"] = path
        sent["op"] = operation

    monkeypatch.setattr("tools.printing.os.name", "nt")
    monkeypatch.setattr("tools.printing.os.startfile", fake_startfile)
    target = tmp_path / "notes.txt"
    target.write_text("hello printer")
    result = PrintTool().execute({"path": str(target)})
    assert "default printer" in result
    assert sent["path"] == str(target)
    assert sent["op"] == "print"


def test_print_allowlist_is_sensible():
    assert ".txt" in PRINTABLE_EXTENSIONS
    assert ".pdf" in PRINTABLE_EXTENSIONS
    assert ".docx" in PRINTABLE_EXTENSIONS


# -- Bedtime: schedule logic ------------------------------------------------

def test_bedtime_plain_window():
    assert in_bedtime_hours(datetime(2026, 8, 14, 9, 0), "09:00", "17:00")
    assert not in_bedtime_hours(datetime(2026, 8, 14, 18, 0), "09:00", "17:00")


def test_bedtime_overnight_window():
    assert in_bedtime_hours(datetime(2026, 8, 14, 23, 0), "22:30", "06:30")
    assert in_bedtime_hours(datetime(2026, 8, 14, 3, 0), "22:30", "06:30")
    assert not in_bedtime_hours(datetime(2026, 8, 14, 12, 0), "22:30", "06:30")


def test_bedtime_boundary_is_half_open():
    assert not in_bedtime_hours(datetime(2026, 8, 14, 9, 0), "09:00", "09:00")
    assert not in_bedtime_hours(datetime(2026, 8, 14, 17, 0), "09:00", "17:00")


def test_bedtime_empty_or_bad_times_are_never_active():
    assert not in_bedtime_hours(datetime(2026, 8, 14, 23, 0), "", "")
    assert not in_bedtime_hours(datetime(2026, 8, 14, 23, 0), "banana", "06:30")


# -- Bedtime: monitor -------------------------------------------------------

class _FakeCfg:
    bedtime_schedule_enabled = False
    bedtime_start = "22:30"
    bedtime_end = "06:30"


def test_bedtime_monitor_manual_on_off(monkeypatch):
    events = []
    cfg = _FakeCfg()
    monitor = BedtimeMonitor(cfg, on_change=lambda active: events.append(active))
    monkeypatch.setattr(bedtime_mod, "set_screen_brightness", lambda level: True)
    monkeypatch.setattr(bedtime_mod, "_first_physical_monitor_brightness", lambda: 90)
    monitor.set_active(True)
    assert monitor.active is True
    assert events == [True]
    monitor.set_active(False)
    assert monitor.active is False
    assert events == [True, False]


def test_bedtime_monitor_no_schedule_never_overrides(monkeypatch):
    cfg = _FakeCfg()  # schedule disabled
    monitor = BedtimeMonitor(cfg)
    monkeypatch.setattr(bedtime_mod, "set_screen_brightness", lambda level: True)
    monkeypatch.setattr(bedtime_mod, "in_bedtime_hours", lambda *a, **k: True)
    monitor.tick()
    assert monitor.active is False  # manual mode: monitor stays hands-off
    monitor.set_active(True)
    assert monitor.active is True
    monitor.tick()
    assert monitor.active is True  # schedule off -> tick never turns it off


def test_bedtime_monitor_schedule_follows_clock(monkeypatch):
    cfg = _FakeCfg()
    cfg.bedtime_schedule_enabled = True
    monitor = BedtimeMonitor(cfg)
    monkeypatch.setattr(bedtime_mod, "set_screen_brightness", lambda level: True)
    monkeypatch.setattr(bedtime_mod, "in_bedtime_hours", lambda *a, **k: True)
    monitor.tick()
    assert monitor.active is True
    monkeypatch.setattr(bedtime_mod, "in_bedtime_hours", lambda *a, **k: False)
    monitor.tick()
    assert monitor.active is False


def test_bedtime_monitor_restores_brightness(monkeypatch):
    brightness_calls = []

    def fake_set(level):
        brightness_calls.append(level)
        return True

    cfg = _FakeCfg()
    monitor = BedtimeMonitor(cfg)
    monkeypatch.setattr(bedtime_mod, "set_screen_brightness", fake_set)
    monkeypatch.setattr(bedtime_mod, "_first_physical_monitor_brightness", lambda: 85)
    monitor.activate()
    assert 30 in brightness_calls
    monitor.deactivate()
    assert 85 in brightness_calls  # original brightness restored


def test_bedtime_tool_status_and_toggle(monkeypatch):
    monitor = BedtimeMonitor(_FakeCfg())
    monkeypatch.setattr(bedtime_mod, "get_bedtime_monitor", lambda on_change=None: monitor)
    assert "OFF" in BedtimeTool().execute({})
    assert "ON" in BedtimeTool().execute({"action": "on"})
    assert "ON" in BedtimeTool().execute({"action": "status"})
    assert "OFF" in BedtimeTool().execute({"action": "off"})
    with pytest.raises(Exception):
        BedtimeTool().execute({"action": "warp"})


# -- Registry ---------------------------------------------------------------

def test_phase37_tools_registered():
    registry = ToolRegistry()
    register_defaults(registry)
    from tools.einstein import register_einstein_tools
    from tools.lighting import register_lighting_tools
    from tools.printing import register_printing_tools
    from tools.bedtime import register_bedtime_tools

    register_einstein_tools(registry)
    register_lighting_tools(registry)
    register_printing_tools(registry)
    register_bedtime_tools(registry)
    assert "einstein" in registry.names()
    assert "lighting_ideas" in registry.names()
    assert "print_document" in registry.names()
    assert "bedtime_mode" in registry.names()


def test_bedtime_tool_not_sensitive():
    from system.security import is_sensitive

    assert not is_sensitive("bedtime_mode")
    assert not is_sensitive("einstein")
    assert not is_sensitive("lighting_ideas")


def test_print_document_is_sensitive():
    from system.security import is_sensitive

    assert is_sensitive("print_document")


def test_all_bedtime_tools_import_clean():
    from tools import build_default_registry  # noqa: F401

    assert EINSTEIN_QUOTES and EINSTEIN_FACTS
