"""
FallbackProvider - chains several providers and tries them in order.

Used in `AI_PROVIDER=auto` mode: if the first free provider is
rate-limited or unreachable (common on free tiers), the next configured
provider is tried automatically, so the user does not hit "no credits /
rate limit" errors as long as at least one free provider works.
"""

from __future__ import annotations

from typing import Callable

from ai.providers.base import BaseProvider, ProviderError
from utils.logger import get_logger

log = get_logger(__name__)


class FallbackProvider(BaseProvider):
    """Try providers in order until one succeeds."""

    name = "auto"

    def __init__(self, providers: list[BaseProvider]):
        self.providers = [p for p in providers if p is not None]
        if not self.providers:
            raise ProviderError("No AI providers were configured.")
        self.is_online = any(p.is_online for p in self.providers)

    def provider_names(self) -> list[str]:
        return [p.name for p in self.providers]

    def chat(self, messages: list[dict], on_token: Callable[[str], None] | None = None) -> str:
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.chat(messages, on_token=on_token)
            except ProviderError as exc:
                errors.append(f"{provider.name}: {exc}")
                log.warning(
                    "Provider %s failed (%s); trying the next one.",
                    provider.name,
                    exc,
                )
        raise ProviderError(self._friendly_message(errors))

    @staticmethod
    def _friendly_message(errors: list[str]) -> str:
        detail = " | ".join(errors)
        return (
            "All AI providers are currently unavailable (usually a free-tier "
            "rate limit or daily quota). Options: add another free API key in "
            ".env (GOOGLE_API_KEY from https://aistudio.google.com/apikey, "
            "GROQ_API_KEY from https://console.groq.com/keys, or a HuggingFace "
            "token), or wait for the daily reset. Details: "
            f"{detail}"
        )
