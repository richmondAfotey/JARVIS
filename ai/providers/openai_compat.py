"""
OpenAI-compatible providers for free-tier AI services.

Several free services expose the exact same chat-completions API as
OpenAI, so they can reuse `OpenAIProvider` with a different key, model
and base URL. Each one is a tiny subclass that just sets a distinct name.

Free tiers (no credit card, rate-limited):
    * Google Gemini  - https://aistudio.google.com/apikey
    * Groq           - https://console.groq.com/keys
    * HuggingFace    - https://huggingface.co/settings/tokens
    * OpenRouter free models (sk-or-v1- key, see .env.example)
"""

from __future__ import annotations

from ai.providers.openai_provider import OpenAIProvider

GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
HUGGINGFACE_BASE_URL = "https://router.huggingface.co/community/v1"
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"

#: name -> (base_url, default model)
FREE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "google": (GOOGLE_BASE_URL, "gemini-flash-latest"),
    "groq": (GROQ_BASE_URL, "llama-3.3-70b-versatile"),
    "huggingface": (HUGGINGFACE_BASE_URL, "meta-llama/Llama-3.3-70B-Instruct"),
    "cerebras": (CEREBRAS_BASE_URL, "gpt-oss-120b"),
}


class OpenAICompatibleProvider(OpenAIProvider):
    """An OpenAI-compatible provider with a custom name and endpoint."""

    def __init__(self, name: str, api_key: str, model: str, base_url: str):
        self.name = name
        super().__init__(api_key=api_key, model=model, base_url=base_url)
