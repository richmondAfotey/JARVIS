"""Tests for Phase 30: local RAG, email tools, scheduler, export, mood and plugins."""

import tempfile
from pathlib import Path

import pytest

from memory.database import Database
from tools import build_default_registry
from tools.base import ToolError


@pytest.fixture()
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture()
def shared_db(monkeypatch, tmp_path):
    """Point every tool's get_shared_database() at a throwaway database."""
    import memory.database as mdb

    fresh = Database(tmp_path / "shared.db")
    monkeypatch.setattr(mdb, "_shared_db", fresh)
    return fresh


def _registry(db=None):
    return build_default_registry(database=db, reminders=None)


# -- RAG --------------------------------------------------------------------

def test_rag_index_and_query(tmp_path):
    from tools.rag import RagIndex

    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.txt").write_text("JARVIS loves coffee and neural networks. " * 40)
    (src / "b.txt").write_text("The weather in London is rainy today. " * 40)
    index = RagIndex()
    out = index.index_folder(src)
    assert out["documents"] == 2

    hits = index.query("what about coffee?", top_k=2)
    assert hits and hits[0]["source"].endswith("a.txt")

    hits2 = index.query("london weather", top_k=1)
    assert hits2[0]["source"].endswith("b.txt")


def test_rag_empty_index_raises(tmp_path):
    from tools.rag import RagIndex

    index = RagIndex()
    with pytest.raises(RuntimeError):
        index.query("anything")


def test_index_documents_tool(shared_db, tmp_path):
    registry = _registry()
    src = tmp_path / "in"
    src.mkdir()
    (src / "x.txt").write_text("Dogs are playful companions. " * 30)
    result = registry.execute("index_documents", {"path": str(src)})
    assert "indexed" in result.lower()

    found = registry.execute("query_documents", {"question": "playful dogs"})
    assert "x.txt" in found


def test_forget_index_tool(shared_db):
    registry = _registry()
    result = registry.execute("forget_index", {})
    assert "cleared" in result.lower()


# -- Recurring scheduler ----------------------------------------------------

def test_schedule_recurring_tool(shared_db):
    registry = _registry()
    result = registry.execute(
        "schedule_recurring",
        {"text": "stand up", "interval": "daily", "start": "in 10 minutes"},
    )
    reminders = shared_db.list_reminders()
    assert reminders and reminders[0]["recurrence"] == "daily"


def test_recurring_reschedules_in_service(db):
    from memory.reminders import ReminderService, next_occurrence

    due = "2026-08-13 10:00"
    rid = db.add_recurring_reminder(
        "stand", due, recurrence="daily", anchor=due
    )
    reminder = db.get_reminder(rid)
    assert reminder["recurrence"] == "daily"

    nxt = next_occurrence(due, "daily", due)
    assert nxt == "2026-08-14T10:00"

    fired = []
    service = ReminderService(db, on_due=lambda r: fired.append(r))
    service._check_due()
    assert fired and fired[0]["id"] == rid
    # Still one live reminder, pushed to the next day.
    assert db.get_reminder(rid)["due_at"] == "2026-08-14T10:00"


def test_next_occurrence_every_unit():
    from memory.reminders import next_occurrence

    assert next_occurrence("2026-08-13 09:00", "every 30 minutes", None) == "2026-08-13T09:30"
    assert next_occurrence("2026-08-13 09:00", "every 2 hours", None) == "2026-08-13T11:00"
    assert next_occurrence("2026-08-13 09:00", "weekly", None) == "2026-08-20T09:00"
    assert next_occurrence("2026-08-13 09:00", None, None) is None


# -- Email tools ------------------------------------------------------------

def test_email_tools_unconfigured():
    import tools.email as em

    tool = em.CheckEmailTool()
    with pytest.raises(ToolError, match="not configured"):
        tool.execute({})


# -- Chat history search ----------------------------------------------------

def test_search_history_tool(db):
    db.start_conversation("test")
    db.save_message("user", "my favourite colour is teal")
    db.save_message("assistant", "noted")
    registry = _registry(db)
    result = registry.execute("search_history", {"query": "teal"})
    assert "teal" in result


def test_search_history_no_match(db):
    registry = _registry(db)
    result = registry.execute("search_history", {"query": "zzzznope"})
    assert "no past messages" in result.lower()


# -- Export -------------------------------------------------------------

def test_export_data_tool(shared_db, tmp_path):
    shared_db.start_conversation("export")
    shared_db.save_message("user", "hello world")
    registry = _registry()
    result = registry.execute("export_data", {"path": str(tmp_path)})
    assert "exported" in result.lower()
    exported = [p for p in tmp_path.iterdir() if p.suffix == ".json"]
    assert exported


# -- Mood log + report ------------------------------------------------------

def test_mood_log_and_report_tool(shared_db):
    from tools.mood import log_mood_emotion, MoodReportTool

    log_mood_emotion("happy", 0.9)
    log_mood_emotion("angry", 0.7)
    rows = shared_db.recent_moods()
    assert {r["emotion"] for r in rows} == {"happy", "angry"}
    counts = shared_db.mood_counts(since_hours=100)
    assert counts["happy"] == 1 and counts["angry"] == 1

    result = MoodReportTool().execute({})
    assert "happy" in result.lower()


def test_mood_report_empty(shared_db):
    from tools.mood import MoodReportTool

    result = MoodReportTool().execute({})
    assert "have not logged" in result.lower()


# -- Briefing ---------------------------------------------------------------

def test_morning_briefing_db(db):
    registry = _registry(db)
    result = registry.execute("morning_briefing", {})
    assert "Good morning" in result


def test_briefing_handles_no_reminders(shared_db):
    registry = _registry()
    result = registry.execute("morning_briefing", {})
    assert "Reminders" in result


# -- Plugin listing ---------------------------------------------------------

def test_list_plugins_tool():
    registry = _registry()
    result = registry.execute("list_plugins", {})
    assert "plugins" in result.lower()


def test_plugin_loader_registers_custom_tool(tmp_path, monkeypatch):
    import config
    from tools.plugins import load_plugins

    folder = tmp_path / "plugins"
    folder.mkdir()
    (folder / "hello.py").write_text(
        "from tools.base import PluginTool\n"
        'class HelloWorldTool(PluginTool):\n'
        '    name = "hello_world"\n'
        '    description = "Say hello."\n'
        '    parameters = {"type": "object", "properties": {}, "required": []}\n'
        '    def execute(self, args):\n'
        '        return "Hello from a plugin!"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config.settings, "plugins_dir", str(folder))
    registry = _registry()
    assert "hello_world" in registry.names()
    assert registry.execute("hello_world", {}) == "Hello from a plugin!"


# -- Voice confirmation tool ------------------------------------------------

def test_confirm_by_voice_unwired():
    from tools.voice_confirm import ConfirmByVoiceTool

    registry = _registry()
    with pytest.raises(ToolError, match="microphone|type yes or no"):
        registry.execute("confirm_by_voice", {"prompt": "Proceed?"})


def test_confirm_by_voice_yes():
    from tools import voice_confirm

    class FakeStt:
        libraries_available = True

        def listen(self, timeout=None):
            return "yes go ahead"

    voice_confirm.wire_stt(FakeStt())
    try:
        from tools.voice_confirm import ConfirmByVoiceTool

        result = ConfirmByVoiceTool().execute({"prompt": "ok?"})
        assert result == "confirmed"
    finally:
        voice_confirm.wire_stt(None)


def test_confirm_by_voice_no():
    from tools import voice_confirm

    class FakeStt:
        libraries_available = True

        def listen(self, timeout=None):
            return "no absolutely not"

    voice_confirm.wire_stt(FakeStt())
    try:
        from tools.voice_confirm import ConfirmByVoiceTool

        assert ConfirmByVoiceTool().execute({"prompt": "ok?"}) == "declined"
    finally:
        voice_confirm.wire_stt(None)