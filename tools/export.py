"""
Data export / backup (Phase 30).

One tool (`export_data`) that dumps the user's notes, memories, reminders
and chat history to JSON (plus a CSV of notes) in a chosen folder, so
their data can be backed up or moved. Exports never overwrite an existing
file - a timestamp is appended.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from config import settings
from memory.database import get_shared_database
from tools.base import Tool, ToolError


def _export_json(target_dir: Path, db) -> Path:
    payload = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "notes": db.list_notes(),
        "memories": db.list_memories(limit=1000),
        "reminders": [
            {
                "text": r["text"],
                "due_at": r["due_at"],
                "recurrence": r.get("recurrence"),
            }
            for r in db.list_reminders()
        ],
        "conversations": [],
    }
    for conv in db.list_conversations():
        messages = _messages_for_conversation(db, conv["id"])
        payload["conversations"].append(
            {"id": conv["id"], "title": conv["title"], "messages": messages}
        )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file = target_dir / f"jarvis-backup-{stamp}.json"
    file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return file


def _messages_for_conversation(db, conversation_id: int) -> list[dict]:
    rows = db.search_messages_in_conversation(conversation_id, limit=10000)
    return rows


def _export_notes_csv(target_dir: Path, db) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file = target_dir / f"jarvis-notes-{stamp}.csv"
    lines = ["title,updated_at,content"]
    for note in db.list_notes():
        content = (note["content"] or "").replace("\n", " ").replace('"', '""')
        lines.append(f'"{note["title"]}","{note["updated_at"]}","{content}"')
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file


class ExportDataTool(Tool):
    name = "export_data"
    description = (
        "Back up JARVIS data (notes, memories, reminders, chat history) to "
        "JSON + CSV files. Use after asking the user where to save them."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Destination folder (defaults to the data folder).",
            }
        },
        "required": [],
    }

    def execute(self, args: dict) -> str:
        db = get_shared_database()
        raw = ((args or {}).get("path") or "").strip()
        target_dir = Path(raw).expanduser() if raw else settings.data_dir / "exports"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"Cannot create export folder: {exc}") from exc

        json_file = _export_json(target_dir, db)
        csv_file = _export_notes_csv(target_dir, db)
        return (
            f"Exported data to:\n- {json_file}\n- {csv_file}"
        )


def register_export_tools(registry) -> None:
    registry.register(ExportDataTool())