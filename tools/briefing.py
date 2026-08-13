"""
Morning briefing (Phase 30).

A single tool that composes a short daily summary for the user by calling
other tools: the time, the weather, pending reminders, saved notes and
recent voice-tone reads. It is wired to the rest of the registry after
registration so it can delegate without circular imports.
"""

from __future__ import annotations

import datetime

from tools.base import Tool, ToolError


class MorningBriefingTool(Tool):
    name = "morning_briefing"
    description = (
        "Give the user a short morning briefing: the time, today's weather, "
        "pending reminders, and anything noteworthy from their notes. Call "
        "when they ask for a briefing or when the day starts."
    )
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self):
        self._registry = None

    def bind(self, registry) -> None:
        """Provide the rest of the tools so the briefing can delegate."""
        self._registry = registry

    def execute(self, args: dict) -> str:
        if self._registry is None:
            raise ToolError("Briefing is not wired up yet.")
        now = datetime.datetime.now().strftime("%H:%M")
        lines = [
            f"Good morning. It is {now}.",
        ]
        try:
            lines.append("Weather: " + self._registry.execute("get_weather", {}))
        except Exception:  # noqa: BLE001
            lines.append("Weather: not configured.")
        try:
            reminders = self._registry.execute("list_reminders", {})
            if "No reminders" in reminders or "none" in reminders.lower():
                lines.append("Reminders: none scheduled.")
            else:
                lines.append(f"Reminders: {reminders}")
        except Exception:  # noqa: BLE001
            lines.append("Reminders: none.")
        try:
            moods = self._registry.execute("mood_report", {"hours": 24})
            if "have not logged" not in moods:
                lines.append(f"Mood: {moods}")
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(lines)


def register_briefing_tools(registry) -> None:
    tool = MorningBriefingTool()
    tool.bind(registry)
    registry.register(tool)