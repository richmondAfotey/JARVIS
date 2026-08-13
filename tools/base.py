"""
Tool base class.

A Tool is a single capability JARVIS can call while answering a message
(clock, calculator, and later: web search, notes, file access...).

Each tool declares:
    * a unique `name` the AI refers to,
    * a human-readable `description` so the AI knows when to use it,
    * a JSON-schema-ish `parameters` map for its arguments,
    * an `execute(args)` method that returns a string result (or raises
      ToolError).

Tools are pure Python and run in the app process. They must never trust
their input blindly - arguments always come from an LLM.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ToolError(RuntimeError):
    """Raised when a tool cannot do its job (bad args, missing data...)."""


class Tool(ABC):
    """Interface every tool must implement."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    def execute(self, args: dict[str, Any]) -> str:
        """Run the tool and return a string result.

        Raises:
            ToolError: if the tool cannot complete.
        """

    # -- Default argument handling ----------------------------------------
    def _arg(self, args: dict[str, Any], key: str, default: Any = None) -> Any:
        """Safely pull an argument out of an LLM-provided dict."""
        if not isinstance(args, dict):
            return default
        return args.get(key, default)


class PluginTool(Tool):
    """Marker base for third-party tools loaded from the `plugins/` folder.

    Plugin authors subclass this (or plain `Tool`) and the loader picks up
    every concrete `Tool` subclass defined in a plugin module. Anything the
    plugin raises through `ToolError` is reported cleanly to the AI.
    """
