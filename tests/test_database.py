"""Tests for the SQLite database layer."""

from memory.database import Database


def test_create_and_load_messages(tmp_path):
    db = Database(tmp_path / "test.db")
    conv_id = db.create_conversation("Test")

    db._current_conversation_id = conv_id
    db.save_message("user", "hello")
    db.save_message("assistant", "hi there")

    messages = db.load_messages(conv_id)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "hi there"
    db.close()


def test_save_without_active_conversation_is_safe(tmp_path):
    db = Database(tmp_path / "test.db")
    assert db.save_message("user", "x") is None
    db.close()


def test_list_and_delete_conversations(tmp_path):
    db = Database(tmp_path / "test.db")
    a = db.create_conversation("A")
    b = db.create_conversation("B")

    convs = db.list_conversations()
    assert {c["id"] for c in convs} == {a, b}

    db.delete_conversation(a)
    convs = db.list_conversations()
    assert {c["id"] for c in convs} == {b}
    db.close()


def test_start_conversation_sets_current(tmp_path):
    db = Database(tmp_path / "test.db")
    conv_id = db.start_conversation("Session")
    assert db.current_conversation_id() == conv_id

    db.save_message("user", "stored under active conversation")
    messages = db.load_messages()  # no explicit id -> uses current
    assert len(messages) == 1
    db.close()


def test_database_persists_across_reopens(tmp_path):
    path = tmp_path / "test.db"
    db = Database(path)
    conv_id = db.start_conversation("Persistent")
    db.save_message("user", "remember me")
    db.close()

    db2 = Database(path)
    db2._current_conversation_id = conv_id
    messages = db2.load_messages(conv_id)
    assert messages[0]["content"] == "remember me"
    db2.close()


def test_resume_latest_conversation_reuses_newest(tmp_path):
    db = Database(tmp_path / "test.db")
    older = db.start_conversation("First")
    newer = db.start_conversation("Second")
    db.save_message("user", "second conversation message")

    resumed = db.resume_latest_conversation()
    assert resumed == newer != older
    assert db.current_conversation_id() == newer
    messages = db.load_messages()
    assert len(messages) == 1
    db.close()


def test_resume_latest_creates_when_empty(tmp_path):
    db = Database(tmp_path / "test.db")
    conversation_id = db.resume_latest_conversation()
    assert conversation_id is not None
    assert db.current_conversation_id() == conversation_id
    db.close()


def test_switch_conversation_changes_current(tmp_path):
    db = Database(tmp_path / "test.db")
    a = db.start_conversation("A")
    b = db.start_conversation("B")
    db.switch_conversation(a)
    assert db.current_conversation_id() == a
    db.save_message("user", "back on A")
    assert [m["content"] for m in db.load_messages()] == ["back on A"]
    db.close()


def test_rename_conversation_sets_title(tmp_path):
    db = Database(tmp_path / "test.db")
    conversation_id = db.start_conversation("Conversation")
    db.rename_conversation(conversation_id, "Unlock the door this weekend")
    preview = db.conversation_preview(conversation_id)
    assert preview["title"] == "Unlock the door this weekend"
    db.close()


def test_conversation_preview_counts_messages(tmp_path):
    db = Database(tmp_path / "test.db")
    conversation_id = db.start_conversation("Chat")
    db.save_message("user", "one")
    db.save_message("assistant", "two")
    preview = db.conversation_preview(conversation_id)
    assert preview["message_count"] == 2
    assert preview["id"] == conversation_id
    db.close()


def test_conversation_preview_none_without_current(tmp_path):
    db = Database(tmp_path / "test.db")
    assert db.conversation_preview() is None
    assert db.current_conversation_id() is None
    db.close()


def test_list_conversations_includes_message_count(tmp_path):
    db = Database(tmp_path / "test.db")
    conversation_id = db.start_conversation("Chat")
    db.save_message("user", "payload")
    conversations = db.list_conversations()
    row = [c for c in conversations if c["id"] == conversation_id][0]
    assert row["message_count"] == 1
    db.close()


def test_delete_active_conversation_then_resume(tmp_path):
    db = Database(tmp_path / "test.db")
    active = db.start_conversation("Active")
    db.save_message("user", "delete me later")
    db.delete_conversation(active)
    resumed = db.resume_latest_conversation()
    assert resumed != active
    assert db.current_conversation_id() == resumed
    db.close()
