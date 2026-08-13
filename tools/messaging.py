"""
Messaging & calling tools (Phase 31) - the free, no-API-key desktop route.

* `send_message` - three channels, all free:
    - **email** via the existing stdlib SMTP client when email is configured,
    - **whatsapp** by opening the official `wa.me` compose link so the user
      just presses send (no automation of their WhatsApp account),
    - **desktop** default: email when the recipient looks like an address,
      otherwise a WhatsApp compose.
* `make_call` - opens the system default phone handler (Phone Link / tel:)
  with the number pre-dialled. The user presses call; no paid voice API.

Everything is honest about what it can and cannot do: JARVIS never pretends
a message was sent when it only opened a compose window, and it reports
clear errors when a channel is not configured.
"""

from __future__ import annotations

import os
import re
import urllib.parse
import webbrowser

from config import settings
from tools.base import Tool, ToolError
from tools.contacts import resolve_recipient

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _looks_like_email(value: str) -> bool:
    return bool(_EMAIL_RE.match((value or "").strip()))


def _whatsapp_compose_url(number: str, message: str) -> str:
    """The official wa.me deep link that opens a pre-filled WhatsApp chat."""
    cleaned = re.sub(r"[^\d]", "", number)
    if not cleaned:
        raise ToolError(f"{number!r} does not look like a phone number.")
    return (
        "https://wa.me/"
        + cleaned
        + "?text="
        + urllib.parse.quote((message or "").strip() or "Hi from JARVIS")
    )


def _send_email(to: str, subject: str, body: str) -> str:
    """Send via the existing SMTP helper when credentials exist."""
    if not (settings.email_user and settings.email_password and settings.email_smtp_host):
        raise ToolError(
            "Email is not configured. Add EMAIL_USER / EMAIL_PASSWORD / "
            "EMAIL_SMTP_HOST to your .env file."
        )
    from tools.email import _send  # noqa: PLC0415

    _send(to, subject, body)
    return f"Email sent to {to}"


class SendMessageTool(Tool):
    name = "send_message"
    description = (
        "Send a message to someone. Channels: 'email' (uses the configured "
        "mail account) or 'whatsapp' (opens WhatsApp with the message "
        "pre-filled - the user taps send). Use 'auto' to pick email for an "
        "email address and WhatsApp for a phone number. The recipient may "
        "be a raw email/phone, or a name from the address book "
        "(e.g. 'Mummy') - use list_contacts to see saved names."
    )
    parameters = {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "Email, phone number, or a saved contact name.",
            },
            "message": {"type": "string", "description": "The message text."},
            "channel": {
                "type": "string",
                "description": "email | whatsapp | auto (default auto).",
            },
        },
        "required": ["recipient", "message"],
    }

    def execute(self, args: dict) -> str:
        recipient = ((args or {}).get("recipient") or "").strip()
        message = ((args or {}).get("message") or "").strip()
        channel = ((args or {}).get("channel") or "auto").strip().lower()
        if not recipient:
            raise ToolError("Please give me a recipient (email or phone).")
        if not message:
            raise ToolError("Please give me a message to send.")

        # "Mummy" style names are resolved through the address book.
        recipient = resolve_recipient(recipient)

        if channel == "auto":
            channel = "email" if _looks_like_email(recipient) else "whatsapp"

        if channel == "email":
            return _send_email(recipient, "Message from JARVIS", message)
        if channel == "whatsapp":
            url = _whatsapp_compose_url(recipient, message)
            _open_url(url)
            return (
                f"Opened WhatsApp with the message ready to send to "
                f"{recipient}. Press send there to deliver it."
            )
        raise ToolError(
            f"Unknown channel {channel!r}. Use email, whatsapp or auto."
        )


class MakeCallTool(Tool):
    name = "make_call"
    description = (
        "Start a phone call to a number by opening the system dialer "
        "(Windows Phone Link / tel: handler). The number is pre-dialled and "
        "the user presses call."
    )
    parameters = {
        "type": "object",
        "properties": {
            "number": {
                "type": "string",
                "description": "Phone number to call, e.g. +1234567890.",
            }
        },
        "required": ["number"],
    }

    def execute(self, args: dict) -> str:
        number = ((args or {}).get("number") or "").strip()
        if not number:
            raise ToolError("Please give me a phone number to call.")
        try:
            # `tel:` opens the default phone handler on Windows/Phone Link.
            os.startfile(f"tel:{urllib.parse.quote(number)}")  # noqa: S606
        except OSError as exc:
            raise ToolError(f"Could not open the dialer: {exc}") from exc
        return f"Opened the dialer for {number}. Press call to dial."


def _open_url(url: str) -> None:
    """Open a URL in the default browser without shell injection."""
    webbrowser.open_new_tab(url)


def register_messaging_tools(registry) -> None:
    registry.register(SendMessageTool())
    registry.register(MakeCallTool())