"""Tests for the Phase 11 notes + reminders tools and the reminder service."""

import threading
import time

import pytest

from memory.database import Database
from memory.reminders import ReminderService
from tools import build_default_registry
from tools.base import ToolError
from tools.notes import (
    CancelReminderTool,
    CreateNoteTool,
    DeleteNoteTool,
    GetNoteTool,
    ListNotesTool,
    ListRemindersTool,
    SetReminderTool,
    parse_due,
)


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db")


# -- parse_due -------------------------------------------------------------

def test_parse_due_relative_minutes():
    out = parse_due("in 5 minutes")
    assert out.startswith("20")


def test_parse_due_relative_hours():
    out = parse_due("in 2 hours")
    assert out.startswith("20")


def test_parse_due_relative_seconds():
    out = parse_due("in 30 seconds")
    assert out.startswith("20")


def test_parse_due_absolute():
    assert parse_due("2026-08-12 15:30") == "2026-08-12 15:30"
    assert parse_due("2026-08-12T09:05") == "2026-08-12 09:05"


def test_parse_due_invalid():
    for bad in ("tomorrow", "soon", "next week", "12 o'clock"):
        try:
            parse_due(bad)
        except ToolError:
            continue
        raise AssertionError(f"Expected ToolError for {bad!r}")


def test_parse_due_invalid_calendar():
    try:
        parse_due("2026-13-40 99:99")
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- notes -----------------------------------------------------------------

def test_create_and_get_note(db):
    result = CreateNoteTool(db).execute({"title": "Ideas", "content": "Build JARVIS"})
    assert "Ideas" in result
    note = GetNoteTool(db).execute({"title": "Ideas"})
    assert "Build JARVIS" in note


def test_create_note_overwrites(db):
    CreateNoteTool(db).execute({"title": "T", "content": "one"})
    CreateNoteTool(db).execute({"title": "T", "content": "two"})
    assert "two" in GetNoteTool(db).execute({"title": "T"})
    assert "one" not in GetNoteTool(db).execute({"title": "T"})


def test_create_note_requires_fields(db):
    try:
        CreateNoteTool(db).execute({"title": "T"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_list_notes(db):
    CreateNoteTool(db).execute({"title": "Alpha", "content": "first note"})
    CreateNoteTool(db).execute({"title": "Beta", "content": "second note"})
    out = ListNotesTool(db).execute({})
    assert "Alpha" in out
    assert "Beta" in out
    assert "2 note(s)" in out


def test_list_notes_empty(db):
    assert "No notes" in ListNotesTool(db).execute({})


def test_get_note_missing(db):
    try:
        GetNoteTool(db).execute({"title": "Nope"})
    except ToolError as exc:
        assert "Nope" in str(exc)
        return
    raise AssertionError("Expected ToolError")


def test_delete_note(db):
    CreateNoteTool(db).execute({"title": "Temp", "content": "x"})
    result = DeleteNoteTool(db).execute({"title": "Temp"})
    assert "Deleted" in result
    assert db.get_note("Temp") is None


def test_delete_note_missing(db):
    try:
        DeleteNoteTool(db).execute({"title": "Gone"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- reminders -------------------------------------------------------------

def test_set_reminder(db):
    class FakeService:
        def __init__(self):
            self.refreshed = 0

        def refresh(self):
            self.refreshed += 1

    fake = FakeService()
    tool = SetReminderTool(db, fake)
    result = tool.execute({"text": "Take the pizza out", "when": "in 30 minutes"})
    assert "Reminder #1" in result
    assert "Take the pizza out" in result
    assert fake.refreshed == 1


def test_list_reminders(db):
    SetReminderTool(db).execute({"text": "Call mum", "when": "in 1 hour"})
    SetReminderTool(db).execute({"text": "Stand up", "when": "2026-08-12 15:30"})
    out = ListRemindersTool(db).execute({})
    assert "2 reminder(s)" in out
    assert "Call mum" in out
    assert "Stand up" in out


def test_list_reminders_empty(db):
    assert "No reminders" in ListRemindersTool(db).execute({})


def test_cancel_reminder(db):
    reminder_id = db.add_reminder("test", "2026-08-12 15:30")
    result = CancelReminderTool(db).execute({"id": reminder_id})
    assert "Cancelled" in result
    assert db.list_reminders() == []


def test_cancel_reminder_missing(db):
    try:
        CancelReminderTool(db).execute({"id": 999})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_set_reminder_bad_time(db):
    try:
        SetReminderTool(db).execute({"text": "x", "when": "next tuesday"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- ReminderService -------------------------------------------------------

def test_service_fires_due_reminder(tmp_path):
    db = Database(tmp_path / "r.db")
    db.add_reminder("Fire me", "2000-01-01 00:00")
    db.add_reminder("Wait for me", "2099-01-01 00:00")
    fired = []
    done = threading.Event()
    service = ReminderService(db, on_due=lambda r: (fired.append(r), done.set()))
    service.start()
    try:
        done.wait(5)
    finally:
        service.stop()
    assert [r["text"] for r in fired] == ["Fire me"]
    assert db.list_reminders()[0]["text"] == "Wait for me"


def test_service_marks_fired_reminder_done(tmp_path):
    db = Database(tmp_path / "r2.db")
    db.add_reminder("Old", "2000-01-01 00:00")
    done = threading.Event()
    service = ReminderService(db, on_due=lambda r: done.set(), poll_seconds=0.05)
    service.start()
    try:
        done.wait(5)
        time.sleep(0.1)
    finally:
        service.stop()
    assert db.list_reminders() == []


# -- registry integration --------------------------------------------------

def test_registry_has_notes_and_reminder_tools(tmp_path):
    db = Database(tmp_path / "reg.db")
    registry = build_default_registry(database=db)
    for name in (
        "create_note",
        "list_notes",
        "get_note",
        "delete_note",
        "set_reminder",
        "list_reminders",
        "cancel_reminder",
    ):
        assert registry.get(name) is not None


def test_build_default_registry_no_args_still_works():
    registry = build_default_registry()
    assert registry.get("create_note") is not None
    assert registry.get("set_reminder") is not None