"""
Bedtime mode tool (Phase 37).

Lets the user (or the AI, on request) turn bedtime mode on or off by voice
or text: dim the screen and make replies quiet/text-only so JARVIS never
interrupts sleep. The heavy lifting lives in `system.bedtime.BedtimeMonitor`
(the schedule thread + screen dimming); this tool is just its voice.

The tool is intentionally NOT approval-gated: it only dims the screen and
mutes JARVIS on the user's own machine - the request itself is the consent.
"""

from __future__ import annotations

from typing import Any

from system.bedtime import get_bedtime_monitor
from tools.base import Tool, ToolError


class BedtimeTool(Tool):
    name = "bedtime_mode"
    description = (
        "Turns bedtime mode on or off: dims the screen and makes JARVIS's "
        "replies quiet (text-only, no spoken audio) so it never interrupts "
        "sleep. Args: action is 'on', 'off' or 'status'. Quiet hours can be "
        "scheduled in Settings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "'on', 'off' or 'status'.",
            }
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        action = (self._arg(args, "action", "") or "").strip().lower()
        monitor = get_bedtime_monitor()
        if action == "on":
            monitor.activate()
            return (
                "Bedtime mode is ON - screen dimmed and replies are quiet. "
                "Say 'goodnight' when you are done talking."
            )
        if action == "off":
            monitor.deactivate()
            return "Bedtime mode is OFF - brightness restored and I will speak normally again."
        if action in ("", "status"):
            return (
                "Bedtime mode is ON (quiet replies + dimmed screen)."
                if monitor.active
                else "Bedtime mode is OFF."
            )
        raise ToolError("Unknown action. Use 'on', 'off' or 'status'.")


def register_bedtime_tools(registry) -> None:
    """Register the Phase 37 bedtime-mode tool on a registry."""
    registry.register(BedtimeTool())
