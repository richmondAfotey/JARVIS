"""
Long-term memory tools (Phase 14).

Let JARVIS remember facts about the user and recall them later:

    * remember        - save a fact (e.g. "my name is Jones")
    * list_memories   - show everything JARVIS remembers
    * forget_memory   - remove a memory by id or by text

Remembered facts are stored in SQLite and injected into the system prompt
on every reply, so JARVIS can naturally use them in later conversations.
"""

from __future__ import annotations

from typing import Any

from tools.base import Tool, ToolError


def _get_db(db):
    if db is not None:
        return db
    from memory.database import get_shared_database

    return get_shared_database()


class RememberTool(Tool):
    name = "remember"
    description = (
        "Saves a fact about the user (their name, preferences, useful "
        "details) to long-term memory so it can be recalled in future "
        "conversations. Use when the user shares something worth keeping."
    )
    parameters = {
        "type": "object",
        "properties": {
            "fact": {
                "type": "string",
                "description": "The fact to remember, as a short sentence.",
            }
        },
        "required": ["fact"],
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        fact = (self._arg(args, "fact", "") or "").strip()
        if not fact:
            raise ToolError("Provide a fact to remember.")
        if self._db.has_memory(fact):
            return "I already remember that."
        self._db.add_memory(fact)
        return f"Remembered: {fact}"


class ListMemoriesTool(Tool):
    name = "list_memories"
    description = "Lists everything JARVIS currently remembers about the user."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        memories = self._db.list_memories(limit=50)
        if not memories:
            return "I do not remember anything yet."
        lines = [f"{len(memories)} remembered fact(s):"]
        for memory in memories:
            lines.append(f"#{memory['id']} - {memory['content']}")
        return "\n".join(lines)


class ForgetMemoryTool(Tool):
    name = "forget_memory"
    description = (
        "Removes a memory from long-term memory, by its id (from "
        "list_memories) or by some of its text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "The memory id to forget."},
            "text": {"type": "string", "description": "Text to match and forget."},
        },
    }

    def __init__(self, db=None) -> None:
        self._db = _get_db(db)

    def execute(self, args: dict[str, Any]) -> str:
        memory_id = self._arg(args, "id", None)
        text = (self._arg(args, "text", "") or "").strip()
        if memory_id is not None:
            try:
                memory_id = int(memory_id)
            except (TypeError, ValueError):
                raise ToolError("id must be a number.")
            if self._db.delete_memory(memory_id):
                return f"Forgot memory #{memory_id}."
            raise ToolError(f"No memory #{memory_id}.")
        if text:
            if self._db.delete_memory_containing(text):
                return f"Forgot memories about {text!r}."
            raise ToolError(f"No memory about {text!r}.")
        raise ToolError("Provide the memory id or some of its text to forget.")


def register_memory_tools(registry, database=None) -> None:
    """Register the Phase 14 long-term memory tools on a registry."""
    registry.register(RememberTool(database))
    registry.register(ListMemoriesTool(database))
    registry.register(ForgetMemoryTool(database))