"""
Mood memory (Phase 30).

Remembers how the user sounded over time. The dashboard logs every
detected voice-tone emotion; the `mood_report` tool summarises the recent
trend so JARVIS can notice patterns (e.g. "you've sounded stressed all
week") and respond accordingly. Honest by design: only logged emotions
that cleared the confidence threshold are counted.
"""

from __future__ import annotations

from collections import Counter

from memory.database import get_shared_database
from tools.base import Tool, ToolError


def log_mood_emotion(emotion: str, confidence: float) -> None:
    """Record a detected tone (used by the dashboard after mic input)."""
    if not emotion or emotion == "neutral":
        return
    db = get_shared_database()
    try:
        db.log_mood(emotion, confidence)
    except Exception:  # noqa: BLE001 - mood logging must never break speech
        pass


class MoodReportTool(Tool):
    name = "mood_report"
    description = (
        "Summarise how the user has sounded recently (from tone of voice) - "
        "e.g. mostly happy today, stressed this week. Use when mood matters."
    )
    parameters = {
        "type": "object",
        "properties": {"hours": {"type": "integer", "description": "Window in hours (default 48)."}},
        "required": [],
    }

    def execute(self, args: dict) -> str:
        hours = max(1, min(24 * 30, int((args or {}).get("hours", 48) or 48)))
        counts = Counter(get_shared_database().mood_counts(since_hours=hours))
        if not counts:
            return (
                "I have not logged any voice-tone reads in the last "
                f"{hours} hours. Use the microphone and I will start keeping "
                "track of how you sound."
            )
        total = sum(counts.values())
        ordered = counts.most_common()
        top_share = ordered[0][1] / total
        summary = ", ".join(f"{emotion} {n}x" for emotion, n in ordered)
        line = f"Over the last {hours} hours you sounded: {summary}."
        if top_share >= 0.5:
            dominant = ordered[0][0]
            note = {
                "happy": "A bright stretch. Nice to hear.",
                "sad": "A tougher stretch. I am here if you want to talk.",
                "angry": "A tense stretch. Let me know if I can help diffuse anything.",
            }.get(dominant, "")
            if note:
                line += f" {note}"
        return line


def register_mood_tools(registry) -> None:
    registry.register(MoodReportTool())