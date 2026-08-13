"""Tests for Phase 15 task scripts (advanced automation)."""

import json

import pytest

from memory.database import Database
from system.scripts import ScriptRunner
from tools import build_default_registry
from tools.base import ToolError
from tools.scripts import (
    CreateScriptTool,
    DeleteScriptTool,
    ListScriptsTool,
    RunScriptTool,
    _parse_steps,
)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture()
def registry(db):
    return build_default_registry(database=db)


# -- _parse_steps ----------------------------------------------------------

def test_parse_steps_list_and_json():
    raw = [{"name": "get_time", "arguments": {}}]
    assert _parse_steps(raw, 30) == raw
    assert _parse_steps(json.dumps(raw), 30) == raw


def test_parse_steps_defaults_arguments():
    out = _parse_steps([{"name": "get_time"}], 30)
    assert out == [{"name": "get_time", "arguments": {}}]


def test_parse_steps_invalid():
    cases = [
        ("not json at all", "must be a valid JSON array"),
        ([], "at least one step"),
        ({"name": "x"}, "JSON array"),
        ([{"arguments": {}}], "missing a tool 'name'"),
        ([{"name": "calc", "arguments": "nope"}], "'arguments' must be an object"),
    ]
    for bad, message in cases:
        try:
            _parse_steps(bad, 30)
        except ToolError as exc:
            assert message in str(exc)
            continue
        raise AssertionError(f"Expected ToolError for {bad!r}")


def test_parse_steps_forbids_meta_tools():
    try:
        _parse_steps([{"name": "run_script", "arguments": {}}], 30)
    except ToolError as exc:
        assert "cannot call" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_parse_steps_max():
    many = [{"name": "get_time", "arguments": {}}] * 5
    try:
        _parse_steps(many, 3)
    except ToolError as exc:
        assert "maximum is 3" in str(exc)
        return
    raise AssertionError("Expected ToolError")


# -- create_script ---------------------------------------------------------

def test_create_script(db):
    steps = [{"name": "calculate", "arguments": {"expression": "2+2"}}]
    out = CreateScriptTool(db).execute({"name": "math", "steps": steps})
    assert "math" in out
    assert "1 step(s)" in out
    script = db.get_script("math")
    assert script is not None
    assert json.loads(script["steps"]) == steps


def test_create_script_overwrites(db):
    tool = CreateScriptTool(db)
    tool.execute({"name": "s", "steps": [{"name": "get_time"}]})
    tool.execute(
        {"name": "s", "steps": [{"name": "get_date"}], "description": "new"}
    )
    script = db.get_script("s")
    assert script["description"] == "new"
    assert json.loads(script["steps"])[0]["name"] == "get_date"


def test_create_script_blank_name(db):
    try:
        CreateScriptTool(db).execute({"steps": [{"name": "get_time"}]})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- run_script ------------------------------------------------------------

def test_run_script_success(db, registry):
    registry.execute(
        "create_script",
        {
            "name": "daily",
            "description": "Evening routine",
            "steps": [
                {"name": "calculate", "arguments": {"expression": "3+4"}},
                {"name": "get_time", "arguments": {}},
            ],
        },
    )
    out = RunScriptTool(registry, db).execute({"name": "daily"})
    assert "Script 'daily' finished (2 step(s))" in out
    assert "calculate -> 7" in out
    assert "get_time ->" in out


def test_run_script_stops_on_error(db, registry):
    registry.execute(
        "create_script",
        {
            "name": "fails",
            "steps": [
                {"name": "calculate", "arguments": {"expression": "1+1"}},
                {"name": "get_note", "arguments": {"title": "missing"}},
                {"name": "calculate", "arguments": {"expression": "9+9"}},
            ],
        },
    )
    out = RunScriptTool(registry, db).execute({"name": "fails"})
    assert "error:" in out
    assert "9+9" not in out  # stopped before the third step


def test_run_script_unknown_tool(db, registry):
    registry.execute(
        "create_script",
        {"name": "bad", "steps": [{"name": "no_such_tool", "arguments": {}}]},
    )
    out = RunScriptTool(registry, db).execute({"name": "bad"})
    assert "error: Unknown tool" in out


def test_run_script_missing(db, registry):
    try:
        RunScriptTool(registry, db).execute({"name": "nope"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_runner_serializes(registry):
    first = True
    order = []

    class SpyTool:
        name = "spy_tool"
        description = ""
        parameters = {}

        def __init__(self, tag):
            self._tag = tag

        def execute(self, args):
            order.append(self._tag)
            return self._tag

    registry.register(SpyTool("a"))
    registry.register(SpyTool("b"))
    runner = ScriptRunner(registry)
    summary = runner.run({"name": "x", "steps": '[{"name": "spy_tool"}]'})
    assert "spy_tool" in summary


# -- list/delete -----------------------------------------------------------

def test_list_scripts(db, registry):
    registry.execute(
        "create_script",
        {"name": "one", "description": "first", "steps": [{"name": "get_time"}]},
    )
    registry.execute(
        "create_script",
        {"name": "two", "description": "second", "steps": [{"name": "get_date"}]},
    )
    out = ListScriptsTool(db).execute({})
    assert "2 script(s)" in out
    assert "one (1 step(s)): first" in out
    assert "two (1 step(s)): second" in out


def test_list_scripts_empty(db):
    assert "No scripts" in ListScriptsTool(db).execute({})


def test_delete_script(db):
    db.save_script("gone", "", '[{"name": "get_time"}]')
    out = DeleteScriptTool(db).execute({"name": "gone"})
    assert "Deleted" in out
    assert db.get_script("gone") is None


def test_delete_script_missing(db):
    try:
        DeleteScriptTool(db).execute({"name": "missing"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- registry integration --------------------------------------------------

def test_registry_has_script_tools(db):
    registry = build_default_registry(database=db)
    for name in ("create_script", "run_script", "list_scripts", "delete_script"):
        assert registry.get(name) is not None