"""Base class for every AI provider.

A provider turns a list of chat messages into a reply. Messages use the
universal OpenAI-style format:

    [
        {"role": "system", "content": "..."},
        {"role": "user",   "content": "..."},
        {"role": "assistant", "content": "..."},
    ]

The provider may yield its reply token-by-token by calling
`on_token(chunk)` so the UI can stream the text live.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from utils.logger import get_logger

log = get_logger(__name__)


class ProviderError(RuntimeError):
    """Raised when a provider fails (network, auth, malformed reply)."""


class BaseProvider(ABC):
    """Interface every provider must implement."""

    name: str = "base"

    #: True when this provider reaches a real AI service (used by the
    #: UI to show online/offline mode). LocalEchoProvider sets this False.
    is_online: bool = True

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Return the assistant's reply text.

        Args:
            messages: OpenAI-style message list (see module docstring).
            on_token: optional callback fired for each text chunk.

        Raises:
            ProviderError: if the provider cannot produce a reply.
        """
