"""
Built-in tools that need no external service.

These prove the tool pipeline end to end and give the AI real, reliable
answers for common local requests (time, date, arithmetic). Later phases
add tools that need APIs or system access (web search, notes, files...).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from tools.base import Tool, ToolError
from utils.helpers import safe_eval_math


class GetTimeTool(Tool):
    name = "get_time"
    description = "Returns the current local time (24-hour format)."
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict[str, Any]) -> str:
        return datetime.now().strftime("%H:%M:%S")


class GetDateTool(Tool):
    name = "get_date"
    description = "Returns today's date, including the weekday."
    parameters = {"type": "object", "properties": {}}

    def execute(self, args: dict[str, Any]) -> str:
        return datetime.now().strftime("%A, %B %d, %Y")


class CalculateTool(Tool):
    name = "calculate"
    description = (
        "Evaluates a simple arithmetic expression such as '12 * (3 + 4)'. "
        "Supported operators: + - * / ** %. Returns the numeric result."
    )
    parameters = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The arithmetic expression to evaluate.",
            }
        },
        "required": ["expression"],
    }

    def execute(self, args: dict[str, Any]) -> str:
        expression = self._arg(args, "expression", "")
        result = safe_eval_math(expression)
        if result == "":
            raise ToolError(
                f"Could not parse {expression!r} as an arithmetic expression."
            )
        return result


class ListToolsTool(Tool):
    """Lets the model discover what it can do mid-conversation."""

    name = "list_tools"
    description = "Returns the names and descriptions of all available tools."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, registry):
        self._registry = registry

    def execute(self, args: dict[str, Any]) -> str:
        lines = []
        for name in self._registry.names():
            tool = self._registry.get(name)
            lines.append(f"- {name}: {tool.description}")
        return "\n".join(lines) if lines else "No tools are available."


def register_defaults(registry) -> None:
    """Register the standard offline-safe tools on a registry."""
    registry.register(GetTimeTool())
    registry.register(GetDateTool())
    registry.register(CalculateTool())
    registry.register(ListToolsTool(registry))
