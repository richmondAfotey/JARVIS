"""
Smart glasses tool (Phase 33).

The `glasses` tool is JARVIS's interface to the user's smart glasses /
wearable. It is honest by design: JARVIS scans for Bluetooth devices,
selects the glasses, and delivers notifications (spoken + native toast).
It never pretends to embed itself into the hardware or reach a vendor
HUD display it cannot touch.
"""

from __future__ import annotations

from config import settings
from glasses.hub import GlassesHub, glasses_prompt_block
from tools.base import Tool, ToolError


class GlassesTool(Tool):
    name = "glasses"
    description = (
        "Interact with the user's smart glasses / wearable. Actions: "
        "'scan' (list Bluetooth devices), 'connect <fragment>' (select the "
        "glasses by name), 'notify <text>' (send a message to the glasses - "
        "shown as a toast and spoken when the device is an audio output), "
        "'status' (what is selected). Be honest: JARVIS talks to paired "
        "hardware and cannot embed itself into the glasses."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "scan | connect | notify | status",
            },
            "device": {
                "type": "string",
                "description": "Name fragment to select on 'connect'.",
            },
            "text": {
                "type": "string",
                "description": "Message to send on 'notify'.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, hub: GlassesHub | None = None) -> None:
        self._hub = hub

    def _hub_ref(self) -> GlassesHub:
        if self._hub is None:
            from voice.text_to_speech import get_tts_service

            tts = get_tts_service(settings) if settings.glasses_enabled else None
            self._hub = GlassesHub(tts=tts)
        return self._hub

    def execute(self, args: dict) -> str:
        action = ((args or {}).get("action") or "").strip().lower()
        if not action:
            raise ToolError("Tell me what to do with the glasses: scan, connect, notify or status.")

        if not settings.glasses_enabled:
            return (
                "Glasses are disabled (GLASSES_ENABLED=false). Enable them "
                "in .env or Settings to use the wearable link."
            )

        hub = self._hub_ref()

        if action == "scan":
            devices = hub.discover()
            if not devices:
                return "No Bluetooth devices visible. Turn on Bluetooth and the glasses, then try again."
            return f"Found {len(devices)} Bluetooth/wearable device(s):\n" + "\n".join(
                f"* {d}" for d in devices
            )

        if action == "connect":
            fragment = ((args or {}).get("device") or "").strip()
            return hub.select(fragment)

        if action == "notify":
            text = ((args or {}).get("text") or "").strip()
            if not text:
                raise ToolError("What should I send to the glasses? Give me some text.")
            return hub.notify(text)

        if action == "status":
            return hub.status()

        raise ToolError(f"Unknown glasses action {action!r}. Use scan, connect, notify or status.")


def register_glasses_tools(registry) -> None:
    """Register the Phase 33 smart-glasses tool on a registry."""
    registry.register(GlassesTool())


__all__ = ["GlassesTool", "register_glasses_tools", "glasses_prompt_block"]