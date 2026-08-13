"""Tests for the Phase 6 tool architecture: registry, parser, agent loop."""

from ai.brain import Brain
from ai.providers.base import BaseProvider
from tools import ToolError, ToolRegistry, ToolCallParser, build_default_registry
from tools.builtin import GetDateTool, GetTimeTool, CalculateTool


def _registry_with_defaults() -> ToolRegistry:
    return build_default_registry()


# -- ToolRegistry ------------------------------------------------------------

def test_registry_registers_and_executes():
    registry = _registry_with_defaults()
    assert "get_time" in registry.names()
    result = registry.execute("calculate", {"expression": "2 + 3 * 4"})
    assert result == "14"


def test_registry_unknown_tool_raises():
    registry = _registry_with_defaults()
    try:
        registry.execute("nope", {})
    except ToolError as exc:
        assert "nope" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_registry_describe_mentions_tools():
    text = _registry_with_defaults().describe_prompt()
    assert "get_time" in text
    assert "TOOL:" in text


def test_duplicate_name_overwrites():
    registry = ToolRegistry()
    registry.register(GetTimeTool())
    registry.register(GetTimeTool())
    assert len(registry) == 1


def test_tool_without_name_rejected():
    class Nameless(GetTimeTool):
        name = ""

    registry = ToolRegistry()
    try:
        registry.register(Nameless())
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- Built-in tools ----------------------------------------------------------

def test_builtin_get_time():
    result = GetTimeTool().execute({})
    assert len(result) == 8  # HH:MM:SS


def test_builtin_get_date():
    result = GetDateTool().execute({})
    assert "," in result and len(result) > 10


def test_builtin_calculate_ok():
    assert CalculateTool().execute({"expression": "12 * 8"}) == "96"


def test_builtin_calculate_bad_input():
    try:
        CalculateTool().execute({"expression": "hello world"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- ToolCallParser ----------------------------------------------------------

def test_parser_strips_tool_line_and_keeps_text():
    parser = ToolCallParser()
    parser.feed("Let me check.\n")
    parser.feed('TOOL: {"name": "get_time", "arguments": {}}\n')
    parser.feed("The time is 12:00:00.")
    parser.finish()
    assert parser.visible_text() == "Let me check.\nThe time is 12:00:00."
    assert parser.tool_calls() == [{"name": "get_time", "arguments": {}}]


def test_parser_tool_line_split_across_chunks():
    parser = ToolCallParser()
    parser.feed('TOOL: {"name": "get_')
    # Partial line is held, not flushed as text.
    assert parser.visible_text() == ""
    parser.feed('time", "arguments": {}}\n')
    parser.finish()
    assert parser.tool_calls() == [{"name": "get_time", "arguments": {}}]
    assert parser.visible_text() == ""


def test_parser_multiple_tool_calls():
    parser = ToolCallParser()
    parser.feed('TOOL: {"name": "get_time", "arguments": {}}\n')
    parser.feed('TOOL: {"name": "get_date", "arguments": {}}\n')
    parser.finish()
    assert len(parser.tool_calls()) == 2


def test_parser_malformed_line_surfaces_as_text():
    parser = ToolCallParser()
    parser.feed("TOOL: not-json\nhi")
    parser.finish()
    assert parser.tool_calls() == []
    assert "not-json" in parser.visible_text()


def test_parser_bad_arguments_default_to_dict():
    parser = ToolCallParser()
    parser.feed('TOOL: {"name": "get_time", "arguments": 5}\n')
    parser.finish()
    assert parser.tool_calls() == [{"name": "get_time", "arguments": {}}]


# -- Brain agent loop --------------------------------------------------------

class ToolingProvider(BaseProvider):
    """Fake provider that plays scripted replies, streaming word-splits."""

    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)
        self.message_sizes = []

    def chat(self, messages, on_token=None):
        text = self.replies.pop(0)
        self.message_sizes.append(len(messages))
        if on_token:
            for i in range(0, len(text), 3):
                on_token(text[i : i + 3])
        return text


def test_brain_tool_loop_runs_tool_and_answers():
    provider = ToolingProvider(
        [
            "One moment.\nTOOL: {\"name\": \"get_time\", \"arguments\": {}}\n",
            "The current time is 12:34:56.",
        ]
    )
    brain = Brain(provider=provider, tools=build_default_registry())
    fired = []
    streamed = []
    reply = brain.respond(
        "What time is it?",
        on_token=streamed.append,
        on_tool=lambda name, args, result: fired.append((name, args, result)),
    )

    assert reply == "The current time is 12:34:56."
    assert len(fired) == 1
    assert fired[0][0] == "get_time"
    assert fired[0][1] == {}
    # Only the final answer is streamed to the UI (no TOOL: line leaks).
    assert "".join(streamed) == "The current time is 12:34:56."
    # The tool result was fed back into the conversation context.
    assert any("get_time ->" in m["content"] for m in brain.history())
    # Two provider calls happened (tool round-trip).
    assert len(provider.message_sizes) == 2
    assert provider.message_sizes[1] > provider.message_sizes[0]


def test_brain_tool_loop_caps_iterations(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "tool_max_iterations", 3)
    provider = ToolingProvider(
        [
            'TOOL: {"name": "get_time", "arguments": {}}\n',
            'TOOL: {"name": "get_time", "arguments": {}}\n',
            'TOOL: {"name": "get_time", "arguments": {}}\n',
            'TOOL: {"name": "get_time", "arguments": {}}\n',
            'TOOL: {"name": "get_time", "arguments": {}}\n',
            'TOOL: {"name": "get_time", "arguments": {}}\n',
        ]
    )
    brain = Brain(provider=provider, tools=build_default_registry())
    reply = brain.respond("What time is it?")
    assert "could not finish" in reply
    assert len(provider.message_sizes) == 3


def test_brain_tool_loop_calculator():
    provider = ToolingProvider(
        [
            'TOOL: {"name": "calculate", "arguments": {"expression": "6 * 7"}}\n',
            "The answer is 42.",
        ]
    )
    brain = Brain(provider=provider, tools=build_default_registry())
    reply = brain.respond("Do the math")
    assert reply == "The answer is 42."


def test_brain_tools_disabled_is_passthrough():
    provider = ToolingProvider(["plain reply"])
    brain = Brain(provider=provider, tools=build_default_registry())
    brain.tools_enabled = False
    reply = brain.respond("hi", on_token=None)
    assert reply == "plain reply"
    assert len(provider.message_sizes) == 1
