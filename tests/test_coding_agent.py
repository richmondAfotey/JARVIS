"""Tests for the Phase 38 coding agent (tools + agent loop, no network)."""

import pytest

from ai.coder import CodingAgent
from ai.providers.base import BaseProvider
from system.security import is_sensitive
from tools import build_default_registry
from tools.base import ToolError
from tools.coding import (
    build_coding_registry,
    _get_code_index,
)


def make_project(tmp_path):
    """A tiny source project with one passing and one failing test."""
    (tmp_path / "app.py").write_text(
        "def calculate_speed(distance, time):\n"
        "    return distance / time\n"
        "\n"
        "def helper():\n"
        "    return 42\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pass.py").write_text(
        "def test_ok():\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_fail.py").write_text(
        "def test_bad():\n    assert 1 == 2\n",
        encoding="utf-8",
    )
    return tmp_path


# -- Registries ---------------------------------------------------------------

def test_coding_registry_excludes_agent_to_avoid_recursion():
    reg = build_coding_registry()
    assert "coding_agent" not in reg.names()
    for name in ("repo_tree", "repo_find", "read_code", "edit_code",
                 "run_tests", "git_status", "code_query", "code_reindex"):
        assert name in reg.names()


def test_main_registry_includes_coding_tools_and_gates_edits():
    reg = build_default_registry()
    assert "coding_agent" in reg.names()
    assert "edit_code" in reg.names()
    # Both write/act, so both must be approval-gated.
    assert is_sensitive("coding_agent")
    assert is_sensitive("edit_code")


# -- Read-only tools ----------------------------------------------------------

def test_repo_tree_lists_layout(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    tree = reg.execute("repo_tree", {})
    assert "app.py" in tree
    assert "tests/" in tree


def test_repo_find_matches_content(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("repo_find", {"pattern": "def calculate_speed"})
    assert "app.py" in result
    assert "def calculate_speed" in result


def test_repo_find_no_match(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("repo_find", {"pattern": "zzz_nothing_here_zzz"})
    assert "No matches" in result


def test_read_code_numbers_lines(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("read_code", {"path": "app.py"})
    assert "1 | def calculate_speed" in result
    assert "app.py" in result


def test_read_code_bad_path_raises(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    with pytest.raises(ToolError):
        reg.execute("read_code", {"path": "missing.py"})


# -- Editing ------------------------------------------------------------------

def test_edit_code_replaces_and_backs_up(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute(
        "edit_code",
        {"path": "app.py", "old": "return distance / time", "new": "return distance / max(time, 0.0)"},
    )
    assert "Edited" in result
    assert (tmp_path / "app.py.bak").exists()
    assert "/ max(time, 0.0)" in (tmp_path / "app.py").read_text(encoding="utf-8")


def test_edit_code_requires_unique_match(tmp_path):
    make_project(tmp_path)
    (tmp_path / "dup.py").write_text("x = 1\ny = 1\n", encoding="utf-8")
    reg = build_coding_registry(project_dir=tmp_path)
    with pytest.raises(ToolError) as exc:
        reg.execute("edit_code", {"path": "dup.py", "old": "1", "new": "2"})
    assert "matches 2 times" in str(exc.value)


# -- Tests --------------------------------------------------------------------

def test_run_tests_passing(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("run_tests", {"target": "tests/test_pass.py"})
    assert "[exit code 0]" in result


def test_run_tests_failing_reports_failure(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("run_tests", {"target": "tests/test_fail.py"})
    assert "[exit code 1]" in result
    assert "test_bad" in result


def test_run_tests_missing_target_raises(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    with pytest.raises(ToolError):
        reg.execute("run_tests", {"target": "tests/nope.py"})


def test_git_status_reports_non_repo(tmp_path):
    make_project(tmp_path)
    reg = build_coding_registry(project_dir=tmp_path)
    result = reg.execute("git_status", {})
    assert "not a git repository" in result


# -- Code RAG -----------------------------------------------------------------

def test_code_query_finds_definition(tmp_path):
    make_project(tmp_path)
    index = _get_code_index(tmp_path, force_rebuild=True)
    results = index.query("function to compute speed", top_k=3)
    assert results
    assert any("app.py" in r["source"] for r in results)


def test_code_query_empty_before_index(tmp_path):
    from tools.coding import CodeIndex

    index = CodeIndex(tmp_path)
    assert index.ready is False
    assert index.query("anything") == []


# -- Agent loop ---------------------------------------------------------------

class FakeProvider(BaseProvider):
    name = "fake"
    is_online = False

    def __init__(self, responses):
        self.responses = list(responses)
        self.seen = []

    def chat(self, messages, on_token=None):
        self.seen.append(messages)
        if not self.responses:
            raise RuntimeError("no more responses")
        return self.responses.pop(0)


def test_coding_agent_runs_tool_then_final_answer(tmp_path):
    make_project(tmp_path)
    provider = FakeProvider(
        [
            'TOOL: {"name": "repo_tree", "arguments": {}}',
            "Done. The project has app.py and a tests folder.",
        ]
    )
    agent = CodingAgent(provider=provider, project_dir=tmp_path)
    tool_calls = []

    reply = agent.run("explore the project", on_tool=lambda n, a, r: tool_calls.append(n))

    assert reply == "Done. The project has app.py and a tests folder."
    assert tool_calls == ["repo_tree"]


def test_coding_agent_resets_between_sessions(tmp_path):
    make_project(tmp_path)
    provider = FakeProvider(
        [
            'TOOL: {"name": "repo_tree", "arguments": {}}',
            "first done",
            'TOOL: {"name": "repo_tree", "arguments": {}}',
            "second done",
        ]
    )
    agent = CodingAgent(provider=provider, project_dir=tmp_path)
    first = agent.run("session one")
    second = agent.run("session two")
    assert first == "first done"
    assert second == "second done"
    # Two sessions, four provider calls -> conversation history was reset.
    assert len(provider.seen) == 4


def test_coding_agent_feeds_tool_errors_back(tmp_path):
    make_project(tmp_path)
    provider = FakeProvider(
        [
            'TOOL: {"name": "read_code", "arguments": {"path": "missing.py"}}',
            "Understood, the file does not exist.",
        ]
    )
    agent = CodingAgent(provider=provider, project_dir=tmp_path)
    reply = agent.run("read a file")
    assert reply == "Understood, the file does not exist."
    # The tool error must have been injected into the conversation.
    injected = [m for m in agent.conversation.messages if "error:" in m.get("content", "")]
    assert injected
