"""
Albert Einstein quotes & facts (Phase 37).

A tiny, offline, free "daily Einstein": a curated list of quotes and facts
served deterministically by date, so the quote of the day is stable. No
internet and no API key required - the AI then comments on it in its reply.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from tools.base import Tool

#: A small, hand-picked set of quotes (kept local + free on purpose).
EINSTEIN_QUOTES = [
    "Imagination is more important than knowledge. Knowledge is limited; imagination encircles the world.",
    "Life is like riding a bicycle. To keep your balance, you must keep moving.",
    "The important thing is not to stop questioning. Curiosity has its own reason for existing.",
    "Anyone who has never made a mistake has never tried anything new.",
    "Try not to become a person of success, but rather try to become a person of value.",
    "The only way to do great work is to love what you do.",
    "Logic will get you from A to B. Imagination will take you everywhere.",
    "A person who never made a mistake never tried anything new.",
    "The true sign of intelligence is not knowledge but imagination.",
    "Everything should be made as simple as possible, but not simpler.",
    "Strive not to be a success, but rather to be of value.",
    "Weakness of attitude becomes weakness of character.",
]

#: A short list of verifiable facts about Einstein's life and work.
EINSTEIN_FACTS = [
    "Einstein published his special theory of relativity in 1905, the same year he earned his doctorate from the University of Zurich.",
    "He won the 1921 Nobel Prize in Physics for his explanation of the photoelectric effect, not for relativity.",
    "His famous equation E=mc^2 was actually a secondary result of his 1905 paper on special relativity.",
    "Einstein was offered the presidency of Israel in 1952 but politely declined.",
    "He played the violin and often used music to think through difficult problems.",
    "When he was offered a job as an examiner at the Swiss patent office, he took it partly because it left his mind free to think.",
    "His brain was removed during the autopsy in 1955 and studied for decades; he had an unusually large parietal lobe.",
    "Einstein was a pacifist who later urged the US to build the atomic bomb out of fear that Nazi Germany would do so first.",
    "He became a US citizen in 1940 after fleeing Nazi Germany for Princeton, New Jersey.",
    "His paper on Brownian motion in 1905 helped prove that atoms actually exist.",
]


class EinsteinTool(Tool):
    name = "einstein"
    description = (
        "Shares a quote or fact from Albert Einstein. Args: kind can be "
        "'quote' (default), 'fact', or 'daily' for the quote of the day "
        "(stable all day). Local and free, no internet needed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "'quote', 'fact', or 'daily'.",
            }
        },
    }

    def execute(self, args: dict[str, Any]) -> str:
        kind = (self._arg(args, "kind", "") or "").strip().lower() or "quote"
        if kind not in ("quote", "fact", "daily"):
            raise ToolError("Unknown kind. Use 'quote', 'fact' or 'daily'.")
        if kind == "fact":
            index = date.today().toordinal() % len(EINSTEIN_FACTS)
            return f"Did you know? {EINSTEIN_FACTS[index]} - Albert Einstein"
        index = date.today().toordinal() % len(EINSTEIN_QUOTES)
        if kind == "daily":
            return f"Quote of the day: \"{EINSTEIN_QUOTES[index]}\" - Albert Einstein"
        return f"\"{EINSTEIN_QUOTES[index]}\" - Albert Einstein"


def register_einstein_tools(registry) -> None:
    """Register the Phase 37 Einstein tool on a registry."""
    registry.register(EinsteinTool())
