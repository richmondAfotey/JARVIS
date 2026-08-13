"""
Reminder service (Phase 11).

A small background thread polls the database for reminders whose due time
has passed and fires `on_due(reminder)` for each one (marking them done so
they only fire once). The UI starts the service and uses the callback to
show a notification and speak the reminder.

Thread-safety: the database is lock-guarded and accepts cross-thread use,
so the poll thread can safely read and update rows.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from typing import Callable

from utils.logger import get_logger

log = get_logger(__name__)

_POLL_SECONDS = 2.0

_RECUR_EVERY = re.compile(r"^\s*every\s+(\d+(?:\.\d+)?)\s+(second|minute|hour|day|week)s?\s*$", re.IGNORECASE)


def next_occurrence(due_at: str, recurrence: str | None, anchor: str | None) -> str | None:
    """Compute the next due time for a repeating reminder.

    Returns None for one-off reminders. Understands "daily", "weekly" and
    "every N unit(s)". ``anchor`` is the first occurrence, ``due_at`` the
    most recent due time that just fired.
    """
    if not recurrence:
        return None
    try:
        last = datetime.fromisoformat(due_at.replace("Z", ""))
    except (ValueError, TypeError):
        return None
    low = recurrence.lower()
    if low == "daily":
        delta = timedelta(days=1)
    elif low == "weekly":
        delta = timedelta(weeks=1)
    else:
        match = _RECUR_EVERY.match(low)
        if not match:
            return None
        amount = float(match.group(1))
        unit = match.group(2).lower()
        delta = timedelta(
            seconds=amount * {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}[unit]
        )
    return (last + delta).isoformat(timespec="minutes")


class ReminderService:
    """Checks for due reminders on a daemon thread."""

    def __init__(
        self,
        db,
        on_due: Callable[[dict], None] | None = None,
        poll_seconds: float = _POLL_SECONDS,
    ) -> None:
        self._db = db
        self._on_due = on_due
        self._poll = float(poll_seconds)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Start the polling thread (no-op if already running)."""
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="reminders", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def refresh(self) -> None:
        """Wake the loop so a just-scheduled reminder is checked promptly."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_due()
            except Exception as exc:  # noqa: BLE001 - a bad check never kills us
                log.debug("Reminder check failed: %s", exc)
            self._wake.wait(self._poll)
            self._wake.clear()

    def _check_due(self) -> None:
        for reminder in self._db.due_reminders():
            if reminder.get("recurrence"):
                # Repeating reminder: keep it alive and push it forward.
                nxt = next_occurrence(
                    reminder["due_at"], reminder["recurrence"], reminder.get("anchor")
                )
                if nxt:
                    self._db.reschedule_reminder(reminder["id"], nxt)
            elif not self._db.mark_reminder_done(reminder["id"]):
                continue  # already handled by another poll
            log.info("Reminder due: %s", reminder["text"])
            if self._on_due:
                self._on_due(reminder)


_shared_service: ReminderService | None = None


def get_shared_service() -> ReminderService:
    """A ReminderService over the shared database (no UI callback)."""
    global _shared_service
    if _shared_service is None:
        from memory.database import get_shared_database

        _shared_service = ReminderService(get_shared_database())
    return _shared_service