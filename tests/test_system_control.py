"""Tests for the Phase 7 computer-control tools."""

import os
import platform
import time
import webbrowser

from tools import build_default_registry, system_control
from tools.base import ToolError
from tools.system_control import (
    ComputerInfoTool,
    ListAppsTool,
    OpenAppTool,
    OpenPathTool,
    OpenUrlTool,
    _launch_command,
)


def _inject_installed_apps(monkeypatch, start=None, uwp=None):
    """Seed the installed-app discovery cache so tests need no real scans."""
    monkeypatch.setattr(system_control, "_APP_SCAN_CACHE_TIME", time.time())
    system_control._APP_SCAN_CACHE["start"] = start or {}
    system_control._APP_SCAN_CACHE["uwp"] = uwp or {}
    monkeypatch.setattr("tools.system_control.shutil.which", lambda name: None)


# -- Catalog --------------------------------------------------------------

def test_launch_command_catalog():
    assert _launch_command("notepad") == ["notepad.exe"]
    assert _launch_command("calculator") == ["calc.exe"]
    assert _launch_command("CALC") == ["calc.exe"]  # case-insensitive


def test_launch_command_finds_path_executable(monkeypatch):
    monkeypatch.setattr("tools.system_control.shutil.which", lambda name: "C:/bin/git.exe")
    assert _launch_command("git") == ["C:/bin/git.exe"]


def test_launch_command_unknown_is_none(monkeypatch):
    monkeypatch.setattr("tools.system_control.shutil.which", lambda name: None)
    assert _launch_command("definitely-not-an-app") is None


# -- ComputerInfoTool -----------------------------------------------------

def test_computer_info_reports_os():
    info = ComputerInfoTool().execute({})
    assert platform.system() in info
    assert len(info) > 10


# -- OpenUrlTool ----------------------------------------------------------

def test_open_url_opens_https(monkeypatch):
    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url, new=0: opened.append(url))
    result = OpenUrlTool().execute({"url": "https://example.com"})
    assert opened == ["https://example.com"]
    assert "Opened" in result


def test_open_url_rejects_unsafe_schemes():
    for bad in ("file:///C:/x", "javascript:alert(1)", "ftp://example.com", "not a url"):
        try:
            OpenUrlTool().execute({"url": bad})
        except ToolError:
            continue
        raise AssertionError(f"Expected ToolError for {bad!r}")


# -- OpenPathTool ---------------------------------------------------------

def test_open_path_missing_raises():
    try:
        OpenPathTool().execute({"path": "C:\\Definitely_Not_Here_XYZ_123"})
    except ToolError as exc:
        assert "not found" in str(exc).lower()
        return
    raise AssertionError("Expected ToolError for a missing path")


def test_open_path_existing_file(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(os, "startfile", lambda path: started.append(path))
    target = tmp_path / "hello.txt"
    target.write_text("hi")
    result = OpenPathTool().execute({"path": str(target)})
    assert started == [str(target)]
    assert "Opened" in result


# -- OpenAppTool ----------------------------------------------------------

def test_open_app_unknown_name(monkeypatch):
    monkeypatch.setattr("tools.system_control.shutil.which", lambda name: None)
    try:
        OpenAppTool().execute({"name": "totally-not-real-app-xyz"})
    except ToolError as exc:
        assert "totally-not-real-app-xyz" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_open_app_known_name_launches(monkeypatch):
    launched = []
    monkeypatch.setattr(
        "tools.system_control.subprocess.Popen", lambda cmd: launched.append(cmd)
    )
    result = OpenAppTool().execute({"name": "notepad"})
    assert launched, "Popen was not called"
    assert launched[0][0].lower().endswith("notepad.exe")
    assert "Opened" in result


def test_open_app_empty_name_raises():
    try:
        OpenAppTool().execute({})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_open_app_multiple_apps_together(monkeypatch):
    launched = []
    monkeypatch.setattr(
        "tools.system_control.subprocess.Popen", lambda cmd: launched.append(cmd)
    )
    result = OpenAppTool().execute({"name": "notepad, calculator"})
    assert len(launched) == 2
    assert any(cmd[0].lower().endswith("notepad.exe") for cmd in launched)
    assert any(cmd[0].lower().endswith("calc.exe") for cmd in launched)
    assert "Opened" in result


def test_open_app_mixed_known_and_unknown(monkeypatch):
    launched = []
    monkeypatch.setattr(
        "tools.system_control.subprocess.Popen", lambda cmd: launched.append(cmd)
    )
    monkeypatch.setattr("tools.system_control.shutil.which", lambda name: None)
    try:
        OpenAppTool().execute({"name": "notepad, totally-bogus-app"})
    except ToolError as exc:
        assert "totally-bogus-app" in str(exc)
        assert len(launched) == 1  # notepad still launched
        return
    raise AssertionError("Expected ToolError")


def test_resolve_name_finds_start_menu_app(monkeypatch):
    _inject_installed_apps(monkeypatch, start={"google chrome": "C:/Chrome.lnk"})
    assert system_control._resolve_name("chrome") == ("startfile", "C:/Chrome.lnk")
    assert system_control._resolve_name("google chrome") == ("startfile", "C:/Chrome.lnk")


def test_resolve_name_finds_uwp_store_app(monkeypatch):
    _inject_installed_apps(monkeypatch, uwp={"photos": "Microsoft.Windows.Photos_!App"})
    assert system_control._resolve_name("photos") == ("uwp", "Microsoft.Windows.Photos_!App")


def test_resolve_name_unknown_still_none(monkeypatch):
    _inject_installed_apps(monkeypatch, start={"google chrome": "C:/Chrome.lnk"})
    assert system_control._resolve_name("definitely-not-installed-xyz") is None


def test_open_app_launches_start_menu_shortcut(monkeypatch):
    started = []
    monkeypatch.setattr(os, "startfile", lambda path: started.append(path))
    _inject_installed_apps(monkeypatch, start={"google chrome": "C:/Chrome.lnk"})
    result = OpenAppTool().execute({"name": "chrome"})
    assert started == ["C:/Chrome.lnk"]
    assert "Opened" in result


def test_open_app_launches_uwp_store_app(monkeypatch):
    launched = []
    monkeypatch.setattr(
        "tools.system_control.subprocess.Popen", lambda cmd: launched.append(cmd)
    )
    _inject_installed_apps(monkeypatch, uwp={"photos": "Microsoft.Windows.Photos_!App"})
    result = OpenAppTool().execute({"name": "photos"})
    assert launched, "Popen was not called"
    assert "AppsFolder" in launched[0][1]
    assert "Opened" in result


def test_installed_app_names_merges_all_sources(monkeypatch):
    _inject_installed_apps(monkeypatch, start={"google chrome": "C:/Chrome.lnk"},
                           uwp={"photos": "id"})
    names = system_control.installed_app_names()
    assert {"notepad", "calculator", "google chrome", "photos"} <= names


# -- ManageWindowsTool ------------------------------------------------------

def test_manage_window_requires_app():
    from tools.system_control import ManageWindowsTool

    tool = ManageWindowsTool()
    try:
        tool.execute({"action": "focus"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_manage_window_unknown_action():
    from tools.system_control import ManageWindowsTool

    tool = ManageWindowsTool()
    try:
        tool.execute({"name": "notepad", "action": "spin-around"})
    except ToolError as exc:
        assert "action" in str(exc).lower()
        return
    raise AssertionError("Expected ToolError")


def test_manage_window_no_window_found(monkeypatch):
    from tools.system_control import ManageWindowsTool

    tool = ManageWindowsTool()
    monkeypatch.setattr(tool, "_find_window", lambda name: None)
    try:
        tool.execute({"name": "notepad", "action": "focus"})
    except ToolError as exc:
        assert "window" in str(exc).lower()
        return
    raise AssertionError("Expected ToolError")


def test_manage_window_focus(monkeypatch):
    from tools.system_control import ManageWindowsTool

    tool = ManageWindowsTool()
    monkeypatch.setattr(tool, "_find_window", lambda name: 1234)
    calls = []
    fake_user32 = type("U", (), {"ShowWindow": lambda s, h, cmd: calls.append(("show", cmd)),
                                 "SetForegroundWindow": lambda s, h: calls.append(("focus",))})()
    monkeypatch.setattr(tool, "_user32", lambda: fake_user32)
    result = tool.execute({"name": "notepad", "action": "focus"})
    assert "front" in result.lower()
    assert ("focus",) in calls


def test_manage_window_snap_left(monkeypatch):
    from tools.system_control import ManageWindowsTool

    tool = ManageWindowsTool()
    monkeypatch.setattr(tool, "_find_window", lambda name: 1234)
    monkeypatch.setattr(tool, "_snap", lambda hwnd, side: None)
    fake_user32 = type("U", (), {"ShowWindow": lambda s, h, cmd: None})()
    monkeypatch.setattr(tool, "_user32", lambda: fake_user32)
    result = tool.execute({"name": "notepad", "action": "snap-left"})
    assert "left" in result.lower()


# -- ListAppsTool ---------------------------------------------------------

def test_list_apps_has_common_names():
    apps = ListAppsTool().execute({})
    assert "notepad" in apps
    assert "calculator" in apps


# -- Registry integration -------------------------------------------------

def test_registry_has_system_tools():
    registry = build_default_registry()
    for name in ("open_app", "open_url", "open_path", "computer_info", "list_apps"):
        assert registry.get(name) is not None


def test_system_tools_execute_via_registry():
    registry = build_default_registry()
    info = registry.execute("computer_info", {})
    assert platform.system() in info
