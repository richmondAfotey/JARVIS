"""
Recurring task scheduler (Phase 30).

Adds repeating reminders on top of the one-off reminders from Phase 11:
"every morning at 9", "every 2 hours", "weekly". The ReminderService keeps
a recurring reminder alive forever - each time it fires it is pushed
forward to the next occurrence instead of being marked done.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from memory.database import get_shared_database
from memory.reminders import next_occurrence
from tools.base import Tool, ToolError

_EVERY = re.compile(
    r"^\s*every\s+(\d+(?:\.\d+)?)\s+(second|minute|hour|day|week)s?\s*$",
    re.IGNORECASE,
)
_DAILY = re.compile(r"^\s*daily\s*$", re.IGNORECASE)
_WEEKLY = re.compile(r"^\s*weekly\s*$", re.IGNORECASE)


def parse_recurrence(interval: str) -> str:
    """Normalise a user-friendly repeat interval into a canonical string."""
    interval = (interval or "").strip()
    if _DAILY.match(interval):
        return "daily"
    if _WEEKLY.match(interval):
        return "weekly"
    if _EVERY.match(interval):
        match = _EVERY.match(interval)
        amount = match.group(1)
        unit = match.group(2).lower()
        return f"every {amount} {unit}{'' if amount == '1' else 's'}"
    raise ToolError(
        "I don't understand that interval. Try 'daily', 'weekly', or "
        "'every 2 hours' / 'every 7 days'."
    )


def first_due(interval: str, start: str = "in 0 minutes") -> str:
    """Compute the first due time from a relative 'in ...' start string."""
    from tools.notes import parse_due

    due = parse_due(start)  # raises ToolError on bad input
    return due


class ScheduleRecurringTool(Tool):
    name = "schedule_recurring"
    description = (
        "Schedule a repeating reminder: 'every morning at 9' style. Give the "
        "task text, the interval (daily / weekly / every N hours/days/...) and "
        "optionally when it should start (e.g. 'in 1 hour')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to remind about."},
            "interval": {
                "type": "string",
                "description": "Repeat interval: daily, weekly, or every N unit(s).",
            },
            "start": {
                "type": "string",
                "description": "When to start, e.g. 'in 1 hour' (default now).",
            },
        },
        "required": ["text", "interval"],
    }

    def execute(self, args: dict) -> str:
        text = ((args or {}).get("text") or "").strip()
        if not text:
            raise ToolError("Please say what to remind about.")
        interval = parse_recurrence((args or {}).get("interval", ""))
        start = (args or {}).get("start", "in 0 minutes") or "in 0 minutes"
        due = first_due(interval, start)

        db = get_shared_database()
        reminder_id = db.add_recurring_reminder(
            text, due, recurrence=interval, anchor=due
        )
        # Wake the scheduler (if the app provided one) so it is checked soon.
        try:
            from memory.reminders import get_shared_service

            get_shared_service().refresh()
        except Exception:  # noqa: BLE001
            pass
        return (
            f"Recurring reminder #{reminder_id} set: {text!r} "
            f"({interval}), first due {due}."
        )


def register_scheduler_tools(registry) -> None:
    registry.register(ScheduleRecurringTool())