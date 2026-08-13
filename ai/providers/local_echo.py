"""
LocalEchoProvider - the offline fallback brain.

Used when no AI provider is configured or when the network is down.
It never pretends to be an AI: it answers a small set of local requests
that work fully offline (clock, simple arithmetic, greetings) and
clearly explains when something needs the online AI instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from ai.providers.base import BaseProvider
from utils.helpers import safe_eval_math

_GREETINGS = ("hello", "hi", "hey", "good morning", "good afternoon", "good evening")


class LocalEchoProvider(BaseProvider):
    """Rule-based offline responder."""

    name = "local"
    is_online = False

    def chat(self, messages: list[dict], on_token: Callable[[str], None] | None = None) -> str:
        user_text = self._last_user_text(messages)
        reply = self._answer(user_text)
        # Stream the reply as if it were generated live (nice for the UI).
        for word in reply.split(" "):
            if on_token:
                on_token(word + " ")
        return reply

    def _last_user_text(self, messages: list[dict]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                return (message.get("content") or "").strip()
        return ""

    def _answer(self, text: str) -> str:
        lowered = text.lower().strip()

        if not lowered:
            return "I did not receive any input. Please type a message."

        if lowered in _GREETINGS or lowered.startswith(_GREETINGS) and len(lowered) < 20:
            return f"Hello. I am running in offline mode, but I am at your service."

        if any(word in lowered for word in ("who are you", "what can you do", "help")):
            return (
                "I am JARVIS, a desktop assistant. In offline mode I can tell the "
                "time, calculate simple arithmetic, and answer basic questions. "
                "Connect an AI provider (see the README) for full conversations."
            )

        if any(word in lowered for word in ("time", "clock")):
            return f"The current time is {datetime.now().strftime('%H:%M:%S')}."

        if any(word in lowered for word in ("date", "today")):
            return f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."

        if any(word in lowered for word in ("calculate", "compute", "math", "=")):
            return self._try_math(lowered)

        # Fallback: be honest that the AI is offline.
        return (
            "I am currently running in offline mode without an AI provider "
            "configured, so I can only handle basic local requests. Add an API "
            "key to your .env file (see README.md) and restart for full "
            "conversational abilities."
        )

    def _try_math(self, text: str) -> str:
        # Pull the first arithmetic-looking segment out of the sentence.
        expression = text
        for marker in ("calculate ", "compute ", "math ", "what is "):
            if marker in text:
                expression = text.split(marker, 1)[-1]
                break
        expression = expression.replace("=", "").strip()

        # Strip common filler words if they were accidentally included.
        for word in ("please", "the", "value of", "answer"):
            expression = expression.replace(word, "")

        result = safe_eval_math(expression)
        if result:
            return f"{expression} = {result}"
        return "I could not parse that as a calculation. Try something like 'calculate 12 * 8'."
