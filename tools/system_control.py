"""
Computer control tools (Phase 7).

Safe, visible, non-destructive actions: launching applications, opening
files and folders, opening web pages, and reporting system information.

Destructive actions (shutdown, killing processes, deleting files) are
deliberately NOT included yet - they need a confirmation flow that comes
in a later phase.

Security notes:
    * Applications are launched with argument lists, never through a
      shell string, so no command injection is possible.
    * URLs must be http(s) - no other scheme is allowed.
    * Paths are validated to exist before being opened.
"""

from __future__ import annotations

import csv
import getpass
import io
import os
import platform
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

from tools.base import Tool, ToolError

#: Well-known apps that can be opened by name. Values are argv lists.
#: These are resolved against PATH at launch time, so no hard-coded
#: absolute paths are needed.
_APP_CATALOG = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "mspaint": ["mspaint.exe"],
    "file explorer": ["explorer.exe"],
    "explorer": ["explorer.exe"],
    "command prompt": ["cmd.exe"],
    "cmd": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "terminal": ["wt.exe"],
    "task manager": ["taskmgr.exe"],
    "taskmgr": ["taskmgr.exe"],
    "control panel": ["control.exe"],
    "control": ["control.exe"],
}

#: Discovered installed apps, cached briefly so listing/opening stays fast.
#: The cache maps "start" -> {name: .lnk path} and "uwp" -> {name: AppID}.
_APP_SCAN_CACHE: dict[str, dict[str, str]] = {"start": {}, "uwp": {}}
_APP_SCAN_CACHE_TIME = 0.0
_APP_SCAN_TTL = 30.0  # seconds


def _launch_command(name: str) -> list[str] | None:
    """Resolve an app name to an argv list, or None if unknown."""
    lowered = (name or "").strip().lower()
    if lowered in _APP_CATALOG:
        return _APP_CATALOG[lowered]
    # Allow executables that live on PATH (e.g. "code", "git", "python").
    found = shutil.which(lowered) or shutil.which(lowered + ".exe")
    if found:
        return [found]
    return None


def _start_menu_roots() -> list[Path]:
    """Folders Windows scans to build the installed-apps Start Menu."""
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    programdata = os.environ.get("PROGRAMDATA")
    if programdata:
        roots.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return roots


def _scan_start_menu() -> dict[str, str]:
    """Every installed app shown in the Start Menu, as {name: .lnk path}."""
    apps: dict[str, str] = {}
    for root in _start_menu_roots():
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            stem = lnk.stem.strip()
            if not stem:
                continue
            apps.setdefault(stem.lower(), str(lnk))
    return apps


def _scan_uwp() -> dict[str, str]:
    """Windows Store (UWP) apps as {name: AppID}, via Get-StartApps."""
    apps: dict[str, str] = {}
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-StartApps | ConvertTo-Csv -NoTypeInformation",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return apps
    if completed.returncode != 0:
        return apps
    try:
        rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    except Exception:
        return apps
    for row in rows:
        name = (row.get("Name") or "").strip()
        app_id = (row.get("AppID") or "").strip()
        if name and app_id:
            apps.setdefault(name.lower(), app_id)
    return apps


def _refresh_app_scan() -> None:
    """Rebuild the installed-app cache if it is stale."""
    global _APP_SCAN_CACHE_TIME
    if time.time() - _APP_SCAN_CACHE_TIME < _APP_SCAN_TTL and _APP_SCAN_CACHE:
        return
    _APP_SCAN_CACHE["start"] = _scan_start_menu()
    #: UWP enumeration is the slow bit (spawns PowerShell); it is also the
    #: least likely to change between calls, so keep it for longer.
    if not _APP_SCAN_CACHE["uwp"] or time.time() - _APP_SCAN_CACHE_TIME > _APP_SCAN_TTL * 2:
        _APP_SCAN_CACHE["uwp"] = _scan_uwp()
    _APP_SCAN_CACHE_TIME = time.time()


def _resolve_name(raw: str) -> tuple[str, str] | None:
    """Resolve a spoken app name to a (kind, target) launch spec.

    ``kind`` is ``"argv"`` (a full command line), ``"startfile"`` (a
    Start Menu .lnk path) or ``"uwp"`` (a Windows Store AppID). The
    built-in catalog and PATH are tried first, then every app installed
    on this PC. Queries are matched exactly first, then by substring
    (the shortest match wins, so "chrome" still finds "Google Chrome").
    """
    query = (raw or "").strip().lower()
    if not query:
        return None
    if query in _APP_CATALOG:
        return ("argv", _APP_CATALOG[query])
    found = shutil.which(query) or shutil.which(query + ".exe")
    if found:
        return ("argv", [found])
    _refresh_app_scan()
    for source, kind in ((_APP_SCAN_CACHE["start"], "startfile"), (_APP_SCAN_CACHE["uwp"], "uwp")):
        for key, target in source.items():
            if query == key:
                return (kind, target)
    best: tuple[int, str, str] | None = None
    for source, kind in ((_APP_SCAN_CACHE["start"], "startfile"), (_APP_SCAN_CACHE["uwp"], "uwp")):
        for key, target in source.items():
            if query in key or key in query:
                if best is None or len(key) < best[0]:
                    best = (len(key), kind, target)
    if best is not None:
        return best[1], best[2]
    return None


def _launch_spec(spec: tuple[str, str], raw_name: str) -> str:
    """Run a launch spec returned by _resolve_name and report the result."""
    kind, target = spec
    if kind == "argv":
        return _run(list(target), raw_name)
    if kind == "startfile":
        try:
            os.startfile(target)
        except OSError as exc:
            raise ToolError(f"Could not launch {raw_name!r}: {exc}") from exc
        return f"Opened {raw_name}."
    if kind == "uwp":
        try:
            subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{target}"])
        except OSError as exc:
            raise ToolError(f"Could not launch {raw_name!r}: {exc}") from exc
        return f"Opened {raw_name}."
    raise ToolError(f"Cannot launch {raw_name!r}.")


def installed_app_names() -> set[str]:
    """All app names open_app currently knows about (for listing)."""
    names = set(_APP_CATALOG)
    _refresh_app_scan()
    names.update(_APP_SCAN_CACHE["start"])
    names.update(_APP_SCAN_CACHE["uwp"])
    return names


def _run(command: list[str], label: str) -> str:
    """Launch an app with the given argv list (no shell)."""
    resolved = command[:]
    resolved[0] = shutil.which(resolved[0]) or resolved[0]
    try:
        subprocess.Popen(resolved)
    except (FileNotFoundError, OSError) as exc:
        raise ToolError(f"Could not launch {label!r}: {exc}") from exc
    return f"Opened {label}."


class OpenAppTool(Tool):
    name = "open_app"
    description = (
        "Launches one or more applications on this computer by name, such as "
        "'notepad', 'calculator', 'chrome', 'spotify', 'whatsapp', or any app "
        "installed on this PC. Separate several apps with commas to open them "
        "together, e.g. name='notepad, calculator'. Use list_apps to see every "
        "app that can be opened."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "The application name, or a comma-separated list of "
                    "applications to open at the same time."
                ),
            }
        },
        "required": ["name"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        name = self._arg(args, "name", "").strip()
        if not name:
            raise ToolError("Specify the name of an application to open.")
        opened: list[str] = []
        failed: list[str] = []
        # Each app is launched on its own; existing apps keep running, so a
        # later call never closes an earlier one (multitasking).
        for raw_name in [n.strip() for n in name.split(",") if n.strip()]:
            spec = _resolve_name(raw_name)
            if spec is None:
                failed.append(raw_name)
                continue
            opened.append(_launch_spec(spec, raw_name))
        if opened and failed:
            raise ToolError(
                f"Opened: {', '.join(opened)}. Unknown: {', '.join(failed)}. "
                f"Known apps: {', '.join(sorted(installed_app_names()))}."
            )
        if failed:
            known = ", ".join(sorted(installed_app_names()))
            raise ToolError(
                f"Unknown application {', '.join(failed)!r}. Apps I can open "
                f"include: {known}. You can also pass any executable that is "
                "on PATH."
            )
        return "Opened " + ", ".join(opened) + "."


class OpenPathTool(Tool):
    name = "open_path"
    description = (
        "Opens a file or folder with its default application. Supports "
        "absolute paths and ~ for the user's home folder."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The file or folder path."}
        },
        "required": ["path"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        path_raw = self._arg(args, "path", "").strip()
        if not path_raw:
            raise ToolError("Specify a path to open.")
        expanded = Path(os.path.expandvars(os.path.expanduser(path_raw)))
        if not expanded.exists():
            raise ToolError(f"Path not found: {expanded}")
        try:
            os.startfile(str(expanded))
        except OSError as exc:
            raise ToolError(f"Could not open {expanded}: {exc}") from exc
        return f"Opened {expanded}."


class OpenUrlTool(Tool):
    name = "open_url"
    description = "Opens a web page in the default browser. Only http:// and https:// URLs are allowed."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The web address to open."}
        },
        "required": ["url"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        url = self._arg(args, "url", "").strip()
        if not url:
            raise ToolError("Specify a URL to open.")
        if not url.lower().startswith(("http://", "https://")):
            raise ToolError("Only http:// and https:// URLs are supported.")
        try:
            webbrowser.open(url, new=2)
        except Exception as exc:  # webbrowser rarely fails, but don't crash
            raise ToolError(f"Could not open {url}: {exc}") from exc
        return f"Opened {url} in the default browser."


class ComputerInfoTool(Tool):
    name = "computer_info"
    description = "Returns information about this computer: OS, version, architecture, hostname, and current user."
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict[str, Any]) -> str:
        return (
            f"{platform.system()} {platform.release()} ({platform.version()}), "
            f"{platform.machine()} architecture, hostname {platform.node()}, "
            f"user {getpass.getuser()}."
        )


class ListAppsTool(Tool):
    name = "list_apps"
    description = (
        "Returns the names of every application installed on this computer "
        "that can be opened with open_app (Start Menu, Windows Store and "
        "PATH executables)."
    )
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict[str, Any]) -> str:
        names = ", ".join(sorted(installed_app_names()))
        return names if names else "No applications are catalogued."


class ManageWindowsTool(Tool):
    """Phase 32: arrange/focus the windows opened by the user's apps.

    Windows can be brought to the front, snapped to a screen edge, or
    minimised. Only the top-level window owned by a running app is moved,
    and every operation is best-effort (some apps own no normal window).
    """

    name = "manage_window"
    description = (
        "Arranges application windows on screen: bring one to the front, "
        "snap it to a screen half, or minimise it. Actions: 'focus', "
        "'snap-left', 'snap-right', 'snap-top', 'snap-bottom', 'maximize', "
        "'minimize'. Example: name='notepad', action='snap-left'. Use with "
        "open_app (multiple apps can run side by side)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Application name (e.g. notepad).",
            },
            "action": {
                "type": "string",
                "description": (
                    "focus | snap-left | snap-right | snap-top | snap-bottom "
                    "| maximize | minimize"
                ),
            },
        },
        "required": ["name", "action"],
    }

    _SW_RESTORE = 9
    _SW_MAXIMIZE = 3
    _SW_MINIMIZE = 6

    def execute(self, args: dict[str, Any]) -> str:
        name = str(self._arg(args, "name", "") or "").strip().lower()
        action = str(self._arg(args, "action", "") or "").strip().lower()
        if not name:
            raise ToolError("Specify an app to manage its window.")
        valid = ("focus", "snap-left", "snap-right", "snap-top",
                 "snap-bottom", "maximize", "minimize")
        if action not in valid:
            raise ToolError(
                f"Unknown action {action!r}. Use one of: {', '.join(valid)}."
            )

        hwnd = self._find_window(name)
        if hwnd is None:
            raise ToolError(
                f"Could not find a window for {name!r}. Is it running? "
                "Open it first with open_app."
            )

        # Normalise the window before moving so snap/maximize land correctly.
        ShowWindow = self._user32().ShowWindow
        ShowWindow(hwnd, self._SW_RESTORE)

        if action == "focus":
            self._bring_to_front(hwnd)
            return f"Brought {name} to the front."
        if action == "minimize":
            ShowWindow(hwnd, self._SW_MINIMIZE)
            return f"Minimised {name}."
        if action == "maximize":
            ShowWindow(hwnd, self._SW_MAXIMIZE)
            return f"Maximised {name}."
        # Snap: move to one screen half, keeping the window's size.
        self._snap(hwnd, action.removeprefix("snap-"))
        return f"Snapped {name} {action.removeprefix('snap-')}."

    # -- Win32 helpers (ctypes, stdlib-only) -------------------------------
    @staticmethod
    def _user32():
        import ctypes

        return ctypes.windll.user32
    def _find_window(self, name: str) -> int | None:
        """Locate the top-level visible window whose process matches `name`."""
        command = _launch_command(name)
        if command is None:
            return None
        exe = command[0].lower()
        import ctypes

        user32 = self._user32()
        process_pid = ctypes.c_ulong()
        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _enum(hwnd, _param):
            if not user32.IsWindowVisible(hwnd):
                return True
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_pid))
            try:
                import psutil

                proc = psutil.Process(process_pid.value)
                proc_exe = (proc.exe() or "").lower()
            except Exception:  # noqa: BLE001 - process may have exited
                proc_exe = ""
            if proc_exe and proc_exe.split("\\")[-1].startswith(
                exe.split("\\")[-1].removesuffix(".exe")
            ):
                found.append(int(hwnd))
                return False  # first match is enough
            return True

        user32.EnumWindows(_enum, 0)
        return found[0] if found else None

    def _bring_to_front(self, hwnd: int) -> None:
        user32 = self._user32()
        user32.SetForegroundWindow(hwnd)

    def _snap(self, hwnd: int, side: str) -> None:
        import ctypes

        user32 = self._user32()
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
        half_w, half_h = width // 2, height // 2
        rect = ctypes.wintypes.RECT()

        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        title = user32.GetSystemMetrics(4)  # caption height approx.
        win_w = max(win_w, half_w - 8)
        win_h = max(win_h, half_h - title - 8)

        if side in ("left",):
            x, y = 0, 0
        elif side in ("right",):
            x, y = width - win_w, 0
        elif side in ("top",):
            x, y = (width - win_w) // 2, 0
        else:  # bottom
            x, y = (width - win_w) // 2, height - win_h
        user32.MoveWindow(hwnd, x, y, win_w, win_h, True)


def register_system_tools(registry) -> None:
    """Register the Phase 7 computer-control tools on a registry."""
    registry.register(OpenAppTool())
    registry.register(OpenPathTool())
    registry.register(OpenUrlTool())
    registry.register(ComputerInfoTool())
    registry.register(ListAppsTool())
    registry.register(ManageWindowsTool())
