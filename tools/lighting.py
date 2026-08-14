"""
Lighting ideas (Phase 37).

Curated, offline lighting recipes for common moods: focus, reading,
relaxing, movie night, bedtime and high energy. Each recipe suggests a
colour temperature, a brightness level and why it helps. JARVIS cannot
control physical smart bulbs from here - these are ideas it offers, and it
can simulate the ambience on the screen via bedtime-mode dimming.

Local + free: no smart-home account, no API key, nothing is sent anywhere.
"""

from __future__ import annotations

from typing import Any

from tools.base import Tool, ToolError

#: Suggested lighting setups, keyed by a short mood name.
LIGHTING_RECIPES = {
    "focus": {
        "label": "Deep focus",
        "kelvin": 5000,
        "brightness": 100,
        "hint": "Cool white, full brightness - mimics daylight and keeps you alert.",
    },
    "reading": {
        "label": "Comfortable reading",
        "kelvin": 3500,
        "brightness": 80,
        "hint": "A soft warm-white from behind or above the page reduces eye strain.",
    },
    "relax": {
        "label": "Unwinding",
        "kelvin": 2700,
        "brightness": 50,
        "hint": "Warm amber at half brightness - signals your body it is time to slow down.",
    },
    "movie": {
        "label": "Movie night",
        "kelvin": 2200,
        "brightness": 20,
        "hint": "Very warm, dim bias lighting behind the screen - big contrast without glare.",
    },
    "bedtime": {
        "label": "Wind-down",
        "kelvin": 1800,
        "brightness": 10,
        "hint": "Candle-warm and nearly off - the ideal ramp into sleep.",
    },
    "energy": {
        "label": "Morning boost",
        "kelvin": 5500,
        "brightness": 100,
        "hint": "Bright, slightly cool white - wakes you up faster than warm light.",
    },
}


class LightingTool(Tool):
    name = "lighting_ideas"
    description = (
        "Suggests a lighting setup for a mood: 'focus', 'reading', 'relax', "
        "'movie', 'bedtime' or 'energy'. Returns colour temperature (Kelvin) "
        "and brightness to aim for. Local and free; JARVIS cannot control "
        "physical bulbs, only suggest. Arg 'mood' is optional."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mood": {
                "type": "string",
                "description": (
                    "focus, reading, relax, movie, bedtime or energy."
                ),
            }
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        mood = (self._arg(args, "mood", "") or "").strip().lower()
        if not mood:
            return (
                "Here are the lighting moods I can suggest: "
                + ", ".join(sorted(LIGHTING_RECIPES))
                + ". Ask me for one, e.g. 'lighting for focus'."
            )
        recipe = LIGHTING_RECIPES.get(mood)
        if recipe is None:
            raise ToolError(
                f"Unknown mood {mood!r}. Available: "
                + ", ".join(sorted(LIGHTING_RECIPES))
            )
        return (
            f"Lighting idea - {recipe['label']}: {recipe['kelvin']}K at "
            f"{recipe['brightness']}% brightness. {recipe['hint']} "
            "(I can only suggest this - I cannot control physical bulbs. "
            "Want me to dim the screen instead for a similar feel?)"
        )


def register_lighting_tools(registry) -> None:
    """Register the Phase 37 lighting-ideas tool on a registry."""
    registry.register(LightingTool())
