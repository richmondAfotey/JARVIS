"""
Chat history search (Phase 30).

A tool that searches every past conversation for a phrase and returns the
matching messages (with their conversation) so JARVIS can dig through
older chats on request.
"""

from __future__ import annotations

from memory.database import get_shared_database
from tools.base import Tool, ToolError


class SearchHistoryTool(Tool):
    name = "search_history"
    description = (
        "Search all past conversations for a word or phrase and return the "
        "matching messages (with which conversation and when)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Phrase to search for."},
            "limit": {"type": "integer", "description": "Max results (default 10)."},
        },
        "required": ["query"],
    }

    def execute(self, args: dict) -> str:
        query = ((args or {}).get("query") or "").strip()
        if not query:
            raise ToolError("Please provide a phrase to search for.")
        limit = max(1, min(25, int((args or {}).get("limit", 10) or 10)))
        rows = get_shared_database().search_messages(query, limit=limit)
        if not rows:
            return f"No past messages matched {query!r}."
        lines = [f"Matches for {query!r}:"]
        for row in rows:
            snippet = row["content"]
            if len(snippet) > 140:
                snippet = snippet[:137] + "..."
            role = "you" if row["role"] == "user" else "JARVIS"
            lines.append(
                f"\n[{row['title']}] {role} ({row['created_at'][:16]}): {snippet}"
            )
        return "\n".join(lines)


def register_chat_search_tools(registry) -> None:
    registry.register(SearchHistoryTool())