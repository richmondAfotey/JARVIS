"""
Tool registry and the streaming tool-call parser.

The registry:
    * collects every registered `Tool`,
    * generates the "AVAILABLE TOOLS" block for the system prompt,
    * executes tools by name with argument validation.

The parser:
    * watches the raw tokens a provider streams back,
    * splits them into two channels: the visible reply text (forwarded to
      the UI) and the tool-call lines (parsed into structured calls).

Tool-call protocol (provider-agnostic, works with any LLM):

    A tool request is exactly one line that starts with `TOOL:` followed
    by a JSON object with `name` and `arguments`, all on a single line:

        TOOL: {"name": "get_time", "arguments": {}}

    The AI is told to output the JSON on one line. Anything else it says
    is normal reply text.
"""

from __future__ import annotations

import json
from typing import Callable

from tools.base import Tool, ToolError
from utils.logger import get_logger

log = get_logger(__name__)

#: Prefix that marks a tool-call line in the model's output.
TOOL_MARKER = "TOOL:"


class ToolRegistry:
    """Holds the tools a Brain can call."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        """Add a tool. Overwrites any existing tool with the same name."""
        if not tool.name:
            raise ToolError("Cannot register a tool without a name.")
        self._tools[tool.name] = tool
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe_prompt(self) -> str:
        """A block of text describing the tools for the system prompt."""
        if not self._tools:
            return ""
        lines = [
            "AVAILABLE TOOLS",
            "You can call tools to get real data or take actions. To call a "
            f"tool, output exactly one line in this format (JSON on a single line):",
            f'TOOL: {{"name": "<tool name>", "arguments": {{...}}}}',
            "You may output several TOOL: lines. The tools then run and you "
            "receive their results, and only then you answer the user. "
            "Never invent tool results.",
            "",
            "Registered tools:",
        ]
        for name in self.names():
            tool = self._tools[name]
            params = json.dumps(tool.parameters, sort_keys=True)
            lines.append(f"- {name}: {tool.description}  arguments: {params}")
        return "\n".join(lines)

    def execute(self, name: str, args: dict) -> str:
        """Run a registered tool. Raises ToolError for unknown tools."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(
                f"Unknown tool '{name}'. Available: {', '.join(self.names()) or 'none'}."
            )
        return tool.execute(args if isinstance(args, dict) else {})


class ToolCallParser:
    """Watches streamed tokens and separates tool calls from reply text.

    Usage:
        parser = ToolCallParser()
        parser.feed(chunk, on_text=my_callback)   # for every token chunk
        parser.finish()                            # when streaming ends
        parser.tool_calls()                        # -> [{"name", "arguments"}]
        parser.visible_text()                      # -> the reply text
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._visible: list[str] = []
        self._calls: list[dict] = []

    def feed(self, chunk: str, on_text: Callable[[str], None] | None = None) -> None:
        """Process a raw token chunk."""
        if not chunk:
            return
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._handle_line(line + "\n", on_text)
        # Flush the partial line unless it could still become a tool call.
        if self._buffer and not self._buffer.lstrip().startswith(TOOL_MARKER):
            self._forward(self._buffer, on_text)
            self._buffer = ""

    def finish(self, on_text: Callable[[str], None] | None = None) -> None:
        """Handle any remaining buffered text after the stream ends."""
        if self._buffer:
            self._handle_line(self._buffer, on_text)
            self._buffer = ""

    def _handle_line(self, line: str, on_text: Callable[[str], None] | None) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if stripped.startswith(TOOL_MARKER):
            call = self._parse_call(stripped[len(TOOL_MARKER):].strip())
            if call is not None:
                self._calls.append(call)
                return
            # Malformed tool line: surface it as ordinary text so nothing
            # the model said is silently swallowed.
            log.warning("Ignoring malformed tool line: %r", stripped)
        self._forward(line, on_text)

    @staticmethod
    def _parse_call(payload: str) -> dict | None:
        try:
            call = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(call, dict) or not isinstance(call.get("name"), str):
            return None
        arguments = call.get("arguments")
        if not isinstance(arguments, dict):
            arguments = {}
        return {"name": call["name"], "arguments": arguments}

    def _forward(self, chunk: str, on_text: Callable[[str], None] | None) -> None:
        self._visible.append(chunk)
        if on_text:
            on_text(chunk)

    def tool_calls(self) -> list[dict]:
        return list(self._calls)

    def visible_text(self) -> str:
        return "".join(self._visible)
