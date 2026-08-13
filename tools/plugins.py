"""
Plugin system (Phase 30).

Lets JARVIS load extra tools from a `plugins/` folder without touching the
core code. Every `.py` file in the folder is imported; any concrete
subclass of `tools.base.Tool` defined there is instantiated and
registered. A bad plugin is reported but never stops the app.

To write a plugin:

    plugins/my_tool.py

        from tools.base import PluginTool

        class HelloWorldTool(PluginTool):
            name = "hello_world"
            description = "Say hello to the sky."
            parameters = {"type": "object", "properties": {}, "required": []}

            def execute(self, args):
                return "Hello from a plugin!"
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from config import PROJECT_ROOT, settings
from tools.base import Tool, ToolError
from utils.logger import get_logger

log = get_logger(__name__)

_cached_plugins: dict[str, str] = {}  # name -> source path (for reporting)


def plugin_dir() -> Path:
    raw = (getattr(settings, "plugins_dir", "") or "").strip()
    return Path(raw).expanduser() if raw else PROJECT_ROOT / "plugins"


def load_plugins(registry) -> tuple[list[str], list[str]]:
    """Load every plugin tool into `registry`. Returns (loaded, skipped)."""
    folder = plugin_dir()
    loaded: list[str] = []
    skipped: list[str] = []
    if not folder.is_dir():
        return loaded, skipped

    for module_path in sorted(folder.glob("*.py")):
        if module_path.name.startswith("_"):
            continue
        name = load_single_plugin(registry, module_path)
        if name is None:
            skipped.append(module_path.name)
            continue
        for tool_name in name:
            loaded.append(f"{tool_name} ({module_path.name})")
    return loaded, skipped


def load_single_plugin(registry, module_path: Path) -> list[str] | None:
    """Import one plugin file and register its tools. None on failure."""
    module_name = f"jarvis_plugin_{module_path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a bad plugin must not crash JARVIS
        log.error("Plugin %s failed to load: %s", module_path.name, exc)
        return None

    names: list[str] = []
    for _, member in inspect.getmembers(module, inspect.isclass):
        if not issubclass(member, Tool) or member is Tool or member.__module__ != module_name:
            continue
        try:
            tool = member()
        except Exception as exc:  # noqa: BLE001
            log.error("Plugin tool %s could not be built: %s", member.__name__, exc)
            continue
        try:
            registry.register(tool)
            _cached_plugins[tool.name] = str(module_path)
            names.append(tool.name)
            log.info("Loaded plugin tool: %s", tool.name)
        except ToolError as exc:
            log.error("Could not register plugin tool %s: %s", tool.name, exc)
    return names


class ListPluginsTool(Tool):
    name = "list_plugins"
    description = "List the tools currently loaded from the plugins folder."
    parameters = {"type": "object", "properties": {}, "required": []}

    def execute(self, args: dict) -> str:
        folder = plugin_dir()
        if not folder.is_dir():
            return "No plugins folder found. Create a 'plugins' directory to add tools."
        names = sorted(_cached_plugins)
        if not names:
            return f"The plugins folder exists but no tools are loaded ({folder})."
        return "Loaded plugin tools:\n- " + "\n- ".join(names)


def register_plugin_tools(registry) -> None:
    load_plugins(registry)
    registry.register(ListPluginsTool())