"""Tests for Phase 16 security monitor + approval gate."""

import pytest

from ai.brain import Brain
from ai.providers.local_echo import LocalEchoProvider
from memory.database import Database
from system.security import SecurityMonitor, is_sensitive, user_approves
from tools import build_default_registry
from tools.base import ToolError


# -- user_approves ---------------------------------------------------------

def test_user_approves():
    assert user_approves("yes")
    assert user_approves("Yes")
    assert user_approves("go ahead")
    assert user_approves("ok, do it")
    assert user_approves("I approve")
    assert user_approves("sure, that's fine")


def test_user_does_not_approve():
    assert not user_approves("what is the weather?")
    assert not user_approves("no")
    assert not user_approves("")
    assert not user_approves("nope, don't")


# -- sensitive tools -------------------------------------------------------

def test_is_sensitive():
    assert is_sensitive("take_screenshot")
    assert is_sensitive("write_file")
    assert is_sensitive("create_folder")
    assert is_sensitive("write_project")
    assert is_sensitive("delete_note")
    assert is_sensitive("forget_memory")
    assert is_sensitive("open_app")
    assert is_sensitive("open_url")
    assert not is_sensitive("get_time")
    assert not is_sensitive("calculate")
    assert not is_sensitive("web_search")


# -- SecurityMonitor -------------------------------------------------------

def test_monitor_records_and_counts():
    monitor = SecurityMonitor()
    monitor.record_tool("get_time", {}, "07:00:00")
    monitor.record_tool("take_screenshot", {}, "saved shot")
    monitor.record("approval", "write_file", "needs approval", level="warning")
    monitor.record("tool", "delete_note", "deleted", level="warning")
    summary = monitor.summary()
    assert summary["counts"].startswith("events 4")
    assert "sensitive 3" in summary["counts"]
    assert "approvals 1" in summary["counts"]
    assert any("take_screenshot" in line for line in summary["feed"])


def test_monitor_ring_bounded():
    monitor = SecurityMonitor()
    for i in range(200):
        monitor.record("info", f"evt{i}", "")
    assert len(monitor.events()) <= 100
    assert monitor.events()[0]["action"] == "evt100"


def test_monitor_persists_to_db(tmp_path):
    db = Database(tmp_path / "sec.db")
    monitor = SecurityMonitor(db)
    monitor.record("approval", "open_url", "blocked", level="warning")
    rows = db.recent_security_events()
    assert len(rows) == 1
    assert rows[0]["category"] == "approval"
    assert rows[0]["action"] == "open_url"


# -- Approval gate in the Brain ----------------------------------------------

def _brain(tmp_path):
    db = Database(tmp_path / "brain.db")
    security = SecurityMonitor(db)
    brain = Brain(provider=LocalEchoProvider(), database=db, security=security)
    return brain, security, db


def test_sensitive_tool_gated_without_approval(tmp_path):
    brain, security, _ = _brain(tmp_path)
    brain._turn_approved = False
    results = brain._run_tool_calls(
        [{"name": "take_screenshot", "arguments": {}}], on_tool=None
    )
    assert "requires your approval" in results[0]
    summary = security.summary()
    assert "approvals 1" in summary["counts"]


def test_sensitive_tool_runs_with_approval(tmp_path):
    brain, security, db = _brain(tmp_path)
    db.save_note("SensitiveNote", "content")
    brain._turn_approved = True  # the user said "yes"
    results = brain._run_tool_calls(
        [{"name": "delete_note", "arguments": {"title": "SensitiveNote"}}], on_tool=None
    )
    assert "Deleted note" in results[0]
    assert db.get_note("SensitiveNote") is None


def test_sensitive_tool_error_still_surfaces(tmp_path):
    brain, _, _ = _brain(tmp_path)
    brain._turn_approved = True
    results = brain._run_tool_calls(
        [{"name": "delete_note", "arguments": {"title": "Missing"}}], on_tool=None
    )
    assert "error:" in results[0]


def test_non_sensitive_tool_not_gated(tmp_path):
    brain, security, _ = _brain(tmp_path)
    brain._turn_approved = False
    results = brain._run_tool_calls(
        [{"name": "get_time", "arguments": {}}], on_tool=None
    )
    assert "requires approval" not in results[0]
    assert "approvals 0" in security.summary()["counts"]


def test_respond_honours_approval_word(tmp_path):
    db = Database(tmp_path / "brain2.db")
    security = SecurityMonitor(db)
    brain = Brain(provider=LocalEchoProvider(), database=db, security=security)
    brain.respond("yes, clean up that note named Nope")
    assert brain._turn_approved  # set by respond before returning (no reset)


# -- registry integration --------------------------------------------------

def test_build_default_registry_has_tools(tmp_path):
    db = Database(tmp_path / "reg.db")
    registry = build_default_registry(database=db)
    assert registry.get("take_screenshot") is not None
    assert registry.get("write_file") is not None


# -- Phase 25 unrestricted mode ----------------------------------------------

def test_unrestricted_mode_bypasses_approval_gate(tmp_path):
    brain, security, _ = _brain(tmp_path)
    brain.set_unrestricted(True)
    brain._turn_approved = False  # even without an explicit "yes"
    results = brain._run_tool_calls(
        [{"name": "take_screenshot", "arguments": {}}], on_tool=None
    )
    assert "requires your approval" not in results[0]
    assert "approvals 0" in security.summary()["counts"]


def test_unrestricted_mode_drops_security_rules(tmp_path):
    brain, _, _ = _brain(tmp_path)
    brain.set_unrestricted(True)
    prompt = brain._build_system_prompt()
    assert "SECURITY:" not in prompt
    assert "Unrestricted mode is enabled" in prompt


def test_unrestricted_mode_toggle_off_restores_gate(tmp_path):
    brain, security, _ = _brain(tmp_path)
    brain.set_unrestricted(True)
    brain.set_unrestricted(False)
    assert "SECURITY:" in brain._build_system_prompt()
    brain._turn_approved = False
    results = brain._run_tool_calls(
        [{"name": "take_screenshot", "arguments": {}}], on_tool=None
    )
    assert "requires your approval" in results[0]
    assert "approvals 1" in security.summary()["counts"]


def test_unrestricted_mode_default_off():
    brain = Brain(provider=LocalEchoProvider())
    assert brain.unrestricted_mode is False