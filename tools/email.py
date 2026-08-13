"""
Email assistant (Phase 30).

Reads, lists and sends email over IMAP and SMTP using only the Python
standard library (`imaplib` / `smtplib` / `email`). Requires credentials
in `.env`:

    EMAIL_USER=you@gmail.com
    EMAIL_PASSWORD=<app password>
    EMAIL_IMAP_HOST=imap.gmail.com
    EMAIL_SMTP_HOST=smtp.gmail.com

Tools are approval-gated (sensitive) because they touch an external
account. Every access is explicit and logged; nothing runs in the
background. Sending is the user's own email with the user's own address.
"""

from __future__ import annotations

import email as _email
import email.policy
import smtplib
from email.message import EmailMessage
from imaplib import IMAP4_SSL

from config import settings
from tools.base import Tool, ToolError


def _configured() -> bool:
    """True when email credentials are present in the settings."""
    return bool(settings.email_user and settings.email_password)


def _imap() -> IMAP4_SSL:
    host = settings.email_imap_host
    if not host:
        raise ToolError("EMAIL_IMAP_HOST is not configured in .env")
    conn = IMAP4_SSL(host)
    conn.login(settings.email_user, settings.email_password)
    return conn


def _fetch_summaries(limit: int, folder: str = "INBOX") -> list[dict]:
    conn = _imap()
    try:
        conn.select(folder)
        _status, data = conn.search(None, "ALL")
        ids = (data[0] or b"").split()
        wanted = ids[-int(limit) :][::-1]
        messages = []
        for msg_id in wanted:
            _status, raw = conn.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not raw or raw[0] is None:
                continue
            parsed = _email.message_from_bytes(
                raw[0][1], policy=email.policy.default
            )
            messages.append(
                {
                    "id": msg_id.decode(),
                    "from": parsed.get("From", ""),
                    "subject": parsed.get("Subject", ""),
                    "date": parsed.get("Date", ""),
                }
            )
        return messages
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _fetch_body(msg_id: str, folder: str = "INBOX") -> dict:
    conn = _imap()
    try:
        conn.select(folder)
        _status, raw = conn.fetch(msg_id.encode(), "(RFC822)")
        if not raw or raw[0] is None:
            raise ToolError(f"Message {msg_id} could not be fetched.")
        parsed = _email.message_from_bytes(raw[0][1], policy=email.policy.default)
        body = ""
        for part in parsed.walk():
            if part.get_content_maintype() == "text":
                payload = part.get_content()
                body = body or (payload or "")
        if parsed.is_multipart() and not body:
            body = "".join(
                part.get_content() or ""
                for part in parsed.walk()
                if part.get_content_maintype() == "text"
            )
        return {
            "id": msg_id,
            "from": parsed.get("From", ""),
            "to": parsed.get("To", ""),
            "subject": parsed.get("Subject", ""),
            "date": parsed.get("Date", ""),
            "body": (body or "")[:4000],
        }
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def _send(to: str, subject: str, body: str) -> None:
    if not settings.email_smtp_host:
        raise ToolError("EMAIL_SMTP_HOST is not configured in .env")
    message = EmailMessage()
    message["From"] = settings.email_user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP_SSL(settings.email_smtp_host) as smtp:
        smtp.login(settings.email_user, settings.email_password)
        smtp.send_message(message)


class CheckEmailTool(Tool):
    name = "check_email"
    description = (
        "List the most recent emails in the user's inbox (sender, subject "
        "and date) so JARVIS can tell them what arrived."
    )
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Max emails (default 5)."}},
        "required": [],
    }

    def execute(self, args: dict) -> str:
        if not _configured():
            raise ToolError(
                "Email is not configured. Set EMAIL_USER, EMAIL_PASSWORD, "
                "EMAIL_IMAP_HOST (and EMAIL_SMTP_HOST to send) in .env"
            )
        limit = min(10, max(1, int((args or {}).get("limit", 5) or 5)))
        try:
            messages = _fetch_summaries(limit)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not reach the mail server: {exc}") from exc
        if not messages:
            return "No emails found in the inbox."
        lines = ["Latest emails:"]
        for m in messages:
            lines.append(f"- [{m['id']}] {m['subject'] or '(no subject)'} (from {m['from']})")
        return "\n".join(lines)


class ReadEmailTool(Tool):
    name = "read_email"
    description = "Fetch the full body of one email by its index id (from check_email)."
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "string", "description": "Email message id."}},
        "required": ["id"],
    }

    def execute(self, args: dict) -> str:
        if not _configured():
            raise ToolError("Email is not configured in .env")
        msg_id = (args or {}).get("id", "").strip()
        if not msg_id:
            raise ToolError("Please provide the email id to read.")
        try:
            message = _fetch_body(msg_id)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not read email {msg_id}: {exc}") from exc
        return (
            f"From: {message['from']}\n"
            f"To: {message['to']}\n"
            f"Subject: {message['subject']}\n"
            f"Date: {message['date']}\n\n{message['body']}"
        )


class SendEmailTool(Tool):
    name = "send_email"
    description = (
        "Send an email from the user's account. The user's words are the "
        "message. Ask for confirmation if the user has not already approved."
    )
    parameters = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Recipient email address."},
            "subject": {"type": "string", "description": "Subject line."},
            "body": {"type": "string", "description": "Message body."},
        },
        "required": ["to", "subject", "body"],
    }

    def execute(self, args: dict) -> str:
        if not _configured():
            raise ToolError("Email is not configured in .env (need SMTP host to send).")
        to = ((args or {}).get("to") or "").strip()
        subject = ((args or {}).get("subject") or "").strip()
        body = ((args or {}).get("body") or "").strip()
        if not to or "@" not in to:
            raise ToolError("Please provide a valid recipient address.")
        try:
            _send(to, subject or "(no subject)", body)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Could not send the email: {exc}") from exc
        return f"Email sent to {to}."


def register_email_tools(registry) -> None:
    registry.register(CheckEmailTool())
    registry.register(ReadEmailTool())
    registry.register(SendEmailTool())