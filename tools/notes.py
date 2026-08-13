"""
Notes and reminders tools (Phase 11).

Notes (persistent, per-title):
    * create_note  - save or overwrite a note by title
    * list_notes   - show every saved note
    * get_note     - read a note's content
    * delete_note  - remove a note

Reminders (persistent, fire at a time):
    * set_reminder   - schedule a reminder ("in 5 minutes" or "2026-08-12 15:30")
    * list_reminders - show pending reminders
    * cancel_reminder - cancel a reminder by id

Everything is stored in the local SQLite database, so notes and reminders
survive restarts. A background ReminderService fires due reminders.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from tools.base import Tool, ToolError

_RELATIVE = re.compile(
    r"^\s*in\s+(\d+(?:\.\d+)?)\s*(second|minute|hour)s?\s*$", re.IGNORECASE
)
_ABSOLUTE = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})\s*$")

_PREVIEW_LIMIT = 120
_DUE_FORMAT = "%Y-%m-%d %H:%M"


def parse_due(when: str) -> str:
    """Turn a user-friendly 'when' into an ISO due timestamp.

    Supported formats:
        * "in 5 minutes" / "in 2 hours" / "in 30 seconds"
        * "2026-08-12 15:30" (24-hour clock)

    Raises ToolError for anything else so the AI can ask for a valid time.
    """
    when = (when or "").strip()
    match = _RELATIVE.match(when)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        seconds = amount * {"second": 1, "minute": 60, "hour": 3600}[unit]
        due = datetime.now() + timedelta(seconds=seconds)
        return due.strftime(_DUE_FORMAT)

    match = _ABSOLUTE.match(when)
    if match:
        year, month, day, hour, minute = (int(g) for g in match.groups())
        try:
            due = datetime(year, month, day, hour, minute)
        except ValueError:
            raise ToolError(
                f"Invalid date/time: {when!r}. Use e.g. '2026-08-12 15:30'."
            )
        return due.strftime(_DUE_FORMAT)

    raise ToolError(
        "I could not understand that time. Say something like 'in 5 minutes', "
        "'in 2 hours', or an exact time like '2026-08-12 15:30'."
    )


def _get_db(db):
    if db is not None:
        return db
    from memory.database import get_shared_database

    return get_shared_database()


def _get_service(reminders):
    if reminders is not None:
        return reminders
    from memory.reminders import get_shared_service

    return get_shared_service()


class CreateNoteTool(Tool):
    name = "create_note"
    description = (
        "Saves a note under a title. If a note with that title already "
        "exists it is overwritten."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title for the note."},
            "content": {"type": "string", "description": "The note's text."},
        },
        "required": ["title", "content"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        title = (self._arg(args, "title", "") or "").strip()
        content = (self._arg(args, "content", "") or "").strip()
        if not title:
            raise ToolError("Provide a title for the note.")
        if not content:
            raise ToolError("Provide some content for the note.")
        self._db.save_note(title, content)
        return f"Saved note {title!r} ({len(content)} chars)."


class ListNotesTool(Tool):
    name = "list_notes"
    description = "Lists every saved note with a short preview of its content."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        notes = self._db.list_notes()
        if not notes:
            return "No notes saved yet."
        lines = [f"{len(notes)} note(s):"]
        for note in notes:
            preview = note["content"].replace("\n", " ").strip()
            if len(preview) > _PREVIEW_LIMIT:
                preview = preview[:_PREVIEW_LIMIT].rstrip() + "..."
            lines.append(f"- {note['title']}: {preview}")
        return "\n".join(lines)


class GetNoteTool(Tool):
    name = "get_note"
    description = "Returns the full content of a saved note by its title."
    parameters = {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "Note title."}},
        "required": ["title"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        title = (self._arg(args, "title", "") or "").strip()
        if not title:
            raise ToolError("Provide the title of the note to read.")
        note = self._db.get_note(title)
        if note is None:
            raise ToolError(f"No note named {title!r}.")
        return f"--- {note['title']} (updated {note['updated_at']}) ---\n{note['content']}"


class DeleteNoteTool(Tool):
    name = "delete_note"
    description = "Deletes a saved note by its title."
    parameters = {
        "type": "object",
        "properties": {"title": {"type": "string", "description": "Note title."}},
        "required": ["title"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        title = (self._arg(args, "title", "") or "").strip()
        if not title:
            raise ToolError("Provide the title of the note to delete.")
        if self._db.delete_note(title):
            return f"Deleted note {title!r}."
        raise ToolError(f"No note named {title!r} to delete.")


class SetReminderTool(Tool):
    name = "set_reminder"
    description = (
        "Schedules a reminder that JARVIS announces when its time arrives. "
        "when accepts 'in 5 minutes', 'in 2 hours', or an exact "
        "'2026-08-12 15:30'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What to be reminded of."},
            "when": {"type": "string", "description": "When it should fire."},
        },
        "required": ["text", "when"],
    }

    def __init__(self, db=None, reminders=None) -> None:
        self._db = _get_db(db)
        self._reminders = _get_service(reminders)

    def execute(self, args: dict[str, Any]) -> str:
        text = (self._arg(args, "text", "") or "").strip()
        when = (self._arg(args, "when", "") or "").strip()
        if not text:
            raise ToolError("Provide what you want to be reminded about.")
        due = parse_due(when)
        reminder_id = self._db.add_reminder(text, due)
        self._reminders.refresh()
        return f"Reminder #{reminder_id} set for {due}: {text}"


class ListRemindersTool(Tool):
    name = "list_reminders"
    description = "Lists all pending (not yet fired) reminders."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        reminders = self._db.list_reminders()
        if not reminders:
            return "No reminders scheduled."
        lines = [f"{len(reminders)} reminder(s):"]
        for reminder in reminders:
            lines.append(f"#{reminder['id']} - {reminder['due_at']}: {reminder['text']}")
        return "\n".join(lines)


class CancelReminderTool(Tool):
    name = "cancel_reminder"
    description = "Cancels a pending reminder by its id (see list_reminders)."
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "The reminder id to cancel."}
        },
        "required": ["id"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        reminder_id = self._arg(args, "id", None)
        try:
            reminder_id = int(reminder_id)
        except (TypeError, ValueError):
            raise ToolError("Provide the reminder id as a number.")
        if self._db.delete_reminder(reminder_id):
            return f"Cancelled reminder #{reminder_id}."
        raise ToolError(f"No pending reminder #{reminder_id}.")


def register_notes_tools(registry, database=None, reminders=None) -> None:
    """Register the Phase 11 notes + reminder tools on a registry."""
    registry.register(CreateNoteTool(database))
    registry.register(ListNotesTool(database))
    registry.register(GetNoteTool(database))
    registry.register(DeleteNoteTool(database))
    registry.register(SetReminderTool(database, reminders))
    registry.register(ListRemindersTool(database))
    registry.register(CancelReminderTool(database))