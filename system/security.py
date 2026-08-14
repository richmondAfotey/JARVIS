"""
Security monitor and hardening (Phase 16).

Two pieces:

1. AUDIT - a `SecurityMonitor` records security-relevant events (every tool
   call, every approval-gated request) in a ring buffer and, when a database
   is given, in the local `security_events` table. The UI panel shows a
   live feed + counters.

2. APPROVAL GATE - a curated set of "sensitive" tools (screenshots, file
   writes, deletion, launching programs/URLs) do not run unless the user's
   current message approves the action. Approval is a simple spoken "yes /
   go ahead / ok..." detected on the user's latest turn; when absent, the
   tool returns a "requires approval" result and JARVIS asks the user.

This is a transparent guard, not a firewall: every decision is logged,
surfaced in the chat and shown on the panel.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from datetime import datetime
from typing import Any

from utils.logger import get_logger

log = get_logger(__name__)

#: Tools that touch the screen, the filesystem, launch things or delete
#: data. These run only with the user's explicit approval.
SENSITIVE_TOOLS = {
    "take_screenshot",
    "write_file",
    "create_folder",
    "write_project",
    "delete_note",
    "delete_script",
    "forget_memory",
    "cancel_reminder",
    "open_app",
    "open_url",
    "open_path",
    "create_poster",
    "design_suit",
    "create_wireframe",
    "apply_patch",
    "check_email",
    "read_email",
    "send_email",
    "export_data",
    "send_message",
    "make_call",
    "manage_window",
    "network_scan",
    "web_recon",
    "password_audit",
    "media_control",
    "export_pdf",
    "print_document",
}

_APPROVAL_RE = re.compile(
    r"\b(yes|yeah|yep|ok|okay|sure|approved|approve|confirm|go ahead|do it|"
    r"allowed|permitted)\b",
    re.IGNORECASE,
)

_RING_SIZE = 100


def is_sensitive(name: str) -> bool:
    return name in SENSITIVE_TOOLS


def user_approves(text: str) -> bool:
    """True if the user's message reads like permission to proceed."""
    text = text or ""
    lower = text.lower()
    if lower == "yes":
        return True
    return bool(_APPROVAL_RE.search(text))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SecurityMonitor:
    def __init__(self, db=None) -> None:
        self._db = db
        self._lock = threading.Lock()
        self._events: deque[dict[str, Any]] = deque(maxlen=_RING_SIZE)
        self._total = 0
        self._sensitive = 0
        self._approvals = 0

    # -- Recording ------------------------------------------------------
    def record(
        self,
        category: str,
        action: str,
        detail: str = "",
        level: str = "info",
        sensitive: bool | None = None,
    ) -> None:
        if sensitive is None:
            sensitive = category in ("tool", "approval")
        event = {
            "ts": _now(),
            "level": level,
            "category": category,
            "action": action,
            "detail": detail,
        }
        with self._lock:
            self._events.append(event)
            self._total += 1
            if sensitive:
                self._sensitive += 1
            if category == "approval":
                self._approvals += 1
        if self._db is not None:
            try:
                self._db.add_security_event(level, category, action, detail)
            except Exception:  # noqa: BLE001 - auditing must never crash the app
                log.exception("Failed to persist security event")

    def record_tool(self, name: str, args: dict, result: str) -> None:
        detail = (result or "")[:80]
        self.record(
            "tool",
            name,
            detail,
            level="warning" if is_sensitive(name) else "info",
            sensitive=is_sensitive(name),
        )

    # -- Reporting ------------------------------------------------------
    def summary(self, feed_lines: int = 5) -> dict:
        with self._lock:
            events = list(self._events)
            total = self._total
            sensitive = self._sensitive
            approvals = self._approvals
        feed = [
            f"{e['ts'][11:19]} {e['category']} {e['action']}"
            for e in reversed(events[:feed_lines])
        ]
        return {
            "feed": feed,
            "counts": (
                f"events {total}  •  sensitive {sensitive}  •  "
                f"approvals {approvals}"
            ),
        }

    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)