"""Anthropic (Claude) chat provider."""

from __future__ import annotations

from typing import Callable

from ai.providers.base import BaseProvider, ProviderError
from utils.logger import get_logger

log = get_logger(__name__)


class AnthropicProvider(BaseProvider):
    """Streams replies from the Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str | None = None):
        if not api_key:
            raise ProviderError("Anthropic API key is missing.")
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'anthropic' package is not installed. Run: pip install anthropic"
            ) from exc

        self.client = Anthropic(api_key=api_key)
        self.model = model or "claude-sonnet-4-20250514"

    def chat(self, messages: list[dict], on_token: Callable[[str], None] | None = None) -> str:
        # Anthropic uses a separate "system" parameter and the rest of the
        # messages must only be user/assistant turns.
        system = "\n\n".join(
            m["content"] for m in messages if m.get("role") == "system"
        )
        turns = [
            {"role": m["role"], "content": m["content"]}
            for m in messages
            if m.get("role") != "system"
        ]

        try:
            with self.client.messages.stream(
                model=self.model,
                max_tokens=2048,
                system=system or None,
                messages=turns,
            ) as stream:
                parts: list[str] = []
                for text in stream.text_stream:
                    parts.append(text)
                    if on_token:
                        on_token(text)
        except Exception as exc:
            log.error("Anthropic request failed: %s", exc)
            raise ProviderError(self._friendly_error(exc)) from exc

        return "".join(parts)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if "401" in lowered or "authentication" in lowered or "api key" in lowered:
            return "Anthropic rejected the API key. Check ANTHROPIC_API_KEY in your .env file."
        if "429" in lowered or "rate" in lowered:
            return "Anthropic rate limit reached. Try again later."
        if "connection" in lowered or "timeout" in lowered:
            return "Could not reach Anthropic. Check your internet connection."
        return f"Anthropic error: {message}"
