"""OpenAI chat provider (also works with OpenAI-compatible servers)."""

from __future__ import annotations

from typing import Callable

from ai.providers.base import BaseProvider, ProviderError
from utils.logger import get_logger

log = get_logger(__name__)


class OpenAIProvider(BaseProvider):
    """Streams replies from the OpenAI chat-completions API."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        if not api_key:
            raise ProviderError("OpenAI API key is missing.")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise ProviderError(
                "The 'openai' package is not installed. Run: pip install openai"
            ) from exc

        headers = None
        if base_url and "openrouter" in base_url.lower():
            # OpenRouter likes to know which app is calling (shows up in
            # their usage dashboard). It is optional and harmless.
            headers = {
                "HTTP-Referer": "https://jarvis-ai.local",
                "X-Title": "JARVIS AI Desktop Assistant",
            }

        self.client = OpenAI(api_key=api_key, base_url=base_url or None, default_headers=headers)
        self.model = model or "gpt-4o-mini"

    def chat(self, messages: list[dict], on_token: Callable[[str], None] | None = None) -> str:
        try:
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
            )
        except Exception as exc:  # network, auth, quota...
            log.error("OpenAI request failed: %s", exc)
            raise ProviderError(self._friendly_error(exc)) from exc

        parts: list[str] = []
        try:
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    if on_token:
                        on_token(delta)
        except Exception as exc:  # streaming interruption
            log.error("OpenAI streaming failed: %s", exc)
            raise ProviderError(self._friendly_error(exc)) from exc

        return "".join(parts)

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if "401" in lowered or "authentication" in lowered or "api key" in lowered:
            return "OpenAI rejected the API key. Check OPENAI_API_KEY in your .env file."
        if "429" in lowered or "quota" in lowered:
            return "OpenAI rate limit or quota reached. Try again later."
        if "connection" in lowered or "timeout" in lowered or "network" in lowered:
            return "Could not reach OpenAI. Check your internet connection."
        return f"OpenAI error: {message}"
