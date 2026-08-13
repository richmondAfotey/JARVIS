"""Tests for Phase 31 messaging & calling tools (send_message, make_call)."""

import pytest

from tools.base import ToolError
from tools.messaging import (
    MakeCallTool,
    SendMessageTool,
    _looks_like_email,
    _whatsapp_compose_url,
)
from tools import build_default_registry


def test_looks_like_email():
    assert _looks_like_email("bob@example.com")
    assert _looks_like_email(" a@b.co ")
    assert not _looks_like_email("+15551234567")
    assert not _looks_like_email("no-at-sign")


def test_whatsapp_url_strips_formatting():
    url = _whatsapp_compose_url("+1 (555) 123-4567", "Hello there")
    assert url.startswith("https://wa.me/15551234567?text=")
    assert "Hello" in url


def test_whatsapp_url_rejects_no_digits():
    with pytest.raises(ToolError, match="phone number"):
        _whatsapp_compose_url("abc", "")


def test_send_message_requires_both_fields():
    tool = SendMessageTool()
    with pytest.raises(ToolError, match="recipient"):
        tool.execute({"message": "hi"})
    with pytest.raises(ToolError, match="message"):
        tool.execute({"recipient": "a@b.co"})


def test_send_message_auto_picks_email_when_unconfigured():
    import tools.messaging as messaging

    # No SMTP credentials -> email channel must fail loudly, not silently.
    tool = SendMessageTool()
    with pytest.raises(ToolError, match="not configured"):
        tool.execute({"recipient": "bob@example.com", "message": "hi", "channel": "auto"})


def test_send_message_email_routes_to_smtp(monkeypatch):
    monkeypatch.setattr("tools.messaging.settings.email_user", "u")
    monkeypatch.setattr("tools.messaging.settings.email_password", "p")
    monkeypatch.setattr("tools.messaging.settings.email_smtp_host", "smtp.example.com")

    import tools.messaging as messaging

    sent = []

    import tools.email as email_mod

    def fake_send(to, subject, body):
        sent.append((to, subject, body))

    monkeypatch.setattr(email_mod, "_send", fake_send)
    tool = SendMessageTool()
    result = tool.execute(
        {"recipient": "bob@example.com", "message": "hello", "channel": "email"}
    )
    assert "sent" in result.lower()
    assert sent and sent[0][0] == "bob@example.com"


def test_send_message_whatsapp_opens_compose(monkeypatch):
    import tools.messaging as messaging

    opened = []
    monkeypatch.setattr(messaging.webbrowser, "open_new_tab", lambda url: opened.append(url))
    tool = SendMessageTool()
    result = tool.execute(
        {"recipient": "+15551234567", "message": "Hi mom", "channel": "whatsapp"}
    )
    assert "press send" in result.lower()
    assert opened and "wa.me/15551234567" in opened[0]


def test_send_message_unknown_channel():
    tool = SendMessageTool()
    with pytest.raises(ToolError, match="channel"):
        tool.execute(
            {"recipient": "bob@example.com", "message": "hi", "channel": "smoke"}
        )


def test_make_call_requires_number():
    tool = MakeCallTool()
    with pytest.raises(ToolError, match="number"):
        tool.execute({})


def test_make_call_opens_dialer(monkeypatch):
    import tools.messaging as messaging

    calls = []
    monkeypatch.setattr(
        messaging.os, "startfile", lambda uri: calls.append(uri)
    )
    tool = MakeCallTool()
    result = tool.execute({"number": "+15551234567"})
    assert "dialer" in result.lower()
    assert calls and calls[0].startswith("tel:")


def test_both_tools_registered():
    registry = build_default_registry()
    assert "send_message" in registry.names()
    assert "make_call" in registry.names()