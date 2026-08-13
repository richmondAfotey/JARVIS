"""Local LLM provider - talks to an OpenAI-compatible server you run
yourself (Ollama, LM Studio, llama.cpp server).

This is the "you own the model" option: the weights live on your machine,
no API key or internet is involved, and the model you pick (including ones
without the usual chat guardrails) decides what it answers. JARVIS simply
forwards your messages to the local endpoint.
"""

from __future__ import annotations

from typing import Callable

from ai.providers.base import ProviderError
from ai.providers.openai_provider import OpenAIProvider
from utils.logger import get_logger

log = get_logger(__name__)

#: Default local endpoint for Ollama.
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"


class LocalLlmProvider(OpenAIProvider):
    """Streams replies from a local OpenAI-compatible LLM server."""

    name = "localllm"

    def __init__(self, model: str, base_url: str = ""):
        # Local servers ignore the key, but the OpenAI SDK requires a
        # non-empty value, so we pass a placeholder.
        super().__init__(
            api_key="local",  # local servers never check this
            model=model,
            base_url=(base_url or DEFAULT_LOCAL_URL).rstrip("/"),
        )

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        message = str(exc)
        lowered = message.lower()
        if any(word in lowered for word in ("connection", "timeout", "refused", "nodename")):
            return (
                "Could not reach your local model server. Start it first "
                "(e.g. 'ollama serve') and make sure LOCAL_LLM_URL in .env "
                "points to it."
            )
        if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
            return (
                "The local model is not installed on your server. Pull it "
                "first (e.g. 'ollama pull <model>') or fix LOCAL_LLM_MODEL "
                "in .env."
            )
        return f"Local LLM error: {message}"