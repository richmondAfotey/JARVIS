"""Tests for Phase 14 long-term memory + preferences persistence."""

import pytest

from ai.brain import Brain
from ai.providers.local_echo import LocalEchoProvider
from memory.database import Database
from tools import build_default_registry
from tools.base import ToolError
from tools.memory import ForgetMemoryTool, ListMemoriesTool, RememberTool


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db")


# -- database --------------------------------------------------------------

def test_add_and_list_memories(db):
    db.add_memory("My name is Jones")
    db.add_memory("I prefer coffee")
    memories = db.list_memories()
    assert len(memories) == 2
    assert any("Jones" in m["content"] for m in memories)


def test_has_memory(db):
    db.add_memory("Favorite color is teal")
    assert db.has_memory("favorite color is teal")  # case-insensitive
    assert not db.has_memory("something else")


def test_delete_memory(db):
    memory_id = db.add_memory("to forget")
    assert db.delete_memory(memory_id)
    assert not db.delete_memory(memory_id)


def test_delete_memory_containing(db):
    db.add_memory("User likes football")
    assert db.delete_memory_containing("football")
    assert db.list_memories() == []


def test_preferences(db):
    assert db.get_preference("tts_enabled") is None
    db.set_preference("tts_enabled", "true")
    db.set_preference("tts_voice", "David")
    db.set_preference("tts_enabled", "false")  # overwrite
    assert db.get_preference("tts_enabled") == "false"
    assert db.get_preference("tts_voice") == "David"
    assert db.all_preferences() == {"tts_enabled": "false", "tts_voice": "David"}


# -- remember --------------------------------------------------------------

def test_remember(db):
    out = RememberTool(db).execute({"fact": "My name is Jones"})
    assert "Remembered" in out
    assert db.has_memory("My name is Jones")


def test_remember_dedupes(db):
    RememberTool(db).execute({"fact": "I like hiking"})
    out = RememberTool(db).execute({"fact": "I like hiking"})
    assert "already" in out.lower()
    assert len(db.list_memories()) == 1


def test_remember_blank(db):
    try:
        RememberTool(db).execute({})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- list_memories ---------------------------------------------------------

def test_list_memories(db):
    db.add_memory("Alpha fact")
    db.add_memory("Beta fact")
    out = ListMemoriesTool(db).execute({})
    assert "2 remembered fact(s)" in out
    assert "Alpha fact" in out
    assert "#1" in out


def test_list_memories_empty(db):
    assert "do not remember" in ListMemoriesTool(db).execute({})


# -- forget_memory ---------------------------------------------------------

def test_forget_by_id(db):
    memory_id = db.add_memory("secret")
    out = ForgetMemoryTool(db).execute({"id": memory_id})
    assert "Forgot" in out
    assert db.list_memories() == []


def test_forget_by_text(db):
    db.add_memory("Likes tea at noon")
    out = ForgetMemoryTool(db).execute({"text": "tea"})
    assert "Forgot" in out
    assert db.list_memories() == []


def test_forget_missing_by_id(db):
    try:
        ForgetMemoryTool(db).execute({"id": 999})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_forget_missing_by_text(db):
    try:
        ForgetMemoryTool(db).execute({"text": "unicorns"})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


def test_forget_blank(db):
    try:
        ForgetMemoryTool(db).execute({})
    except ToolError:
        return
    raise AssertionError("Expected ToolError")


# -- Brain integration -----------------------------------------------------

def test_system_prompt_includes_memories(tmp_path):
    database = Database(tmp_path / "brain.db")
    database.add_memory("The user's name is Zara")
    brain = Brain(provider=LocalEchoProvider(), database=database)
    brain.respond("hello")
    system = brain.conversation.messages[0]["content"]
    assert "Zara" in system
    assert "long-term memory" in system


def test_system_prompt_refreshed_after_remember(tmp_path):
    database = Database(tmp_path / "brain2.db")
    brain = Brain(provider=LocalEchoProvider(), database=database)
    brain.tools.execute("remember", {"fact": "The user is a pilot"})
    brain.respond("hello again")
    system = brain.conversation.messages[0]["content"]
    assert "pilot" in system


# -- registry integration --------------------------------------------------

def test_registry_has_memory_tools(tmp_path):
    database = Database(tmp_path / "reg.db")
    registry = build_default_registry(database=database)
    for name in ("remember", "list_memories", "forget_memory"):
        assert registry.get(name) is not None