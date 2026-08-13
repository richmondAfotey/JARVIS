"""Tests for the Phase 32 contacts address book (save_contact etc)."""

import pytest

from config import settings
from tools.base import ToolError
from tools.contacts import (
    ForgetContactTool,
    ListContactsTool,
    SaveContactTool,
    load_contacts,
    resolve_recipient,
    save_contacts,
)
from tools import build_default_registry
from tools.messaging import SendMessageTool


@pytest.fixture(autouse=True)
def clean_book(tmp_path, monkeypatch):
    """Point the address book at a temp file for every test."""
    target = tmp_path / "contacts.json"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr("tools.contacts._contacts_file", lambda: target)
    yield target
    if target.exists():
        target.unlink()


def test_save_and_reload(clean_book):
    result = SaveContactTool().execute(
        {"name": "Mummy", "phone": "+233201234567"}
    )
    assert "Saved" in result
    book = load_contacts()
    assert book["mummy"]["phone"] == "+233201234567"


def test_save_requires_name_or_number():
    with pytest.raises(ToolError, match="name"):
        SaveContactTool().execute({})
    with pytest.raises(ToolError, match="phone|email"):
        SaveContactTool().execute({"name": "Bob"})


def test_save_updates_existing(clean_book):
    SaveContactTool().execute({"name": "Mummy", "phone": "+1"})
    SaveContactTool().execute({"name": "Mummy", "email": "m@x.co"})
    entry = load_contacts()["mummy"]
    assert entry["phone"] == "+1"
    assert entry["email"] == "m@x.co"


def test_list_contacts(clean_book):
    SaveContactTool().execute({"name": "Mummy", "phone": "+2331"})
    SaveContactTool().execute({"name": "Dad", "email": "dad@x.co"})
    result = ListContactsTool().execute({})
    assert "Mummy" in result and "Dad" in result
    assert "2 contact(s)" in result


def test_list_empty(clean_book):
    assert "empty" in ListContactsTool().execute({})


def test_forget_contact(clean_book):
    SaveContactTool().execute({"name": "Mummy", "phone": "+1"})
    result = ForgetContactTool().execute({"name": "Mummy"})
    assert "Forgot" in result
    assert load_contacts() == {}
    with pytest.raises(ToolError, match="No contact"):
        ForgetContactTool().execute({"name": "Mummy"})


def test_resolve_contact_name(clean_book):
    save_contacts({"mummy": {"name": "Mummy", "phone": "+233201234567", "email": ""}})
    assert resolve_recipient("Mummy") == "+233201234567"
    assert resolve_recipient("mummy") == "+233201234567"


def test_resolve_contact_falls_back_to_email(clean_book):
    save_contacts({"mum": {"name": "Mum", "phone": "", "email": "m@x.co"}})
    assert resolve_recipient("Mum") == "m@x.co"


def test_resolve_raw_recipient_unchanged():
    assert resolve_recipient("+233201234567") == "+233201234567"
    assert resolve_recipient("bob@example.com") == "bob@example.com"


def test_resolve_unknown_name_errors(clean_book):
    with pytest.raises(ToolError, match="address book"):
        resolve_recipient("Mummy")


def test_unknown_name_lists_known(clean_book):
    save_contacts({"dad": {"name": "Dad", "phone": "+1", "email": ""}})
    with pytest.raises(ToolError, match="Dad"):
        resolve_recipient("Mummy")


def test_corrupt_book_is_tolerated(clean_book):
    clean_book.write_text("{not json", encoding="utf-8")
    assert load_contacts() == {}


def test_send_message_resolves_contact_name(clean_book, monkeypatch):
    import tools.messaging as messaging

    save_contacts({"mummy": {"name": "Mummy", "phone": "+233201234567", "email": ""}})
    opened = []
    monkeypatch.setattr(messaging.webbrowser, "open_new_tab", lambda url: opened.append(url))
    result = SendMessageTool().execute({"recipient": "Mummy", "message": "Hi", "channel": "whatsapp"})
    assert "press send" in result.lower()
    assert opened and "wa.me/233201234567" in opened[0]


def test_contacts_tools_registered():
    registry = build_default_registry()
    for name in ("save_contact", "list_contacts", "forget_contact"):
        assert name in registry.names()