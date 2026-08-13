"""
Conversation manager - holds the current chat history.

Keeps an OpenAI-style list of messages:
    [{"role": "system", "content": "..."}, {"role": "user", ...}, ...]

The history is trimmed to the most recent `max_messages` turns so very
long conversations do not blow past the AI model's context window.
"""

from __future__ import annotations

from typing import Callable

from utils.logger import get_logger

log = get_logger(__name__)

_SummaryFn = Callable[[list[dict]], list[dict]]


class Conversation:
    def __init__(
        self,
        system_prompt: str = "",
        max_messages: int = 40,
        summarizer: _SummaryFn | None = None,
    ):
        self.system_prompt = system_prompt
        self.max_messages = max_messages
        self._summarizer = summarizer
        self.messages: list[dict] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def add_user(self, text: str) -> None:
        """Record the user's latest message."""
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        """Record the assistant's latest reply."""
        self.messages.append({"role": "assistant", "content": text})
        self._trim()

    def add_raw(self, role: str, content: str) -> None:
        """Append a raw message (used for internal agent-loop steps).

        Unlike add_user/add_assistant this does not get persisted as a
        real chat message - it is context only (e.g. tool-call lines and
        tool results during a multi-step answer).
        """
        self.messages.append({"role": role, "content": content})
        self._trim()

    def _trim(self) -> None:
        """Keep only the last `max_messages` turns (system prompt first).

        Phase 30: when long, old turns are compressed into a summary first
        (via the optional `summarizer`) so information survives trimming.
        """
        # The real system prompt is pinned by exact content so generated
        # summary notes (also role "system") never hide it or pile up.
        system = [m for m in self.messages if m.get("content") == self.system_prompt]
        if not system and self.system_prompt:
            system = [{"role": "system", "content": self.system_prompt}]
        turns = [m for m in self.messages if m["role"] != "system"]
        if self._summarizer is not None:
            turns = self._summarizer(turns)
        # A summarizer may emit one fresh synthetic summary "system" message.
        summary = [m for m in turns if m["role"] == "system"]
        turns = [m for m in turns if m["role"] != "system"]
        if len(turns) > self.max_messages:
            turns = turns[-self.max_messages:]
        self.messages = system + summary + turns

    def clear(self) -> None:
        """Start a fresh conversation (keeping the system prompt)."""
        self.messages = []
        if self.system_prompt:
            self.messages.append({"role": "system", "content": self.system_prompt})

    def set_system_prompt(self, prompt: str) -> None:
        """Replace the system prompt (used to refresh remembered facts)."""
        self.system_prompt = prompt
        replaced = False
        for message in self.messages:
            if message["role"] == "system":
                message["content"] = prompt
                replaced = True
                break
        if not replaced and prompt:
            self.messages.insert(0, {"role": "system", "content": prompt})

    def history(self) -> list[dict]:
        """Return a copy of the message list (excluding the system prompt)."""
        return [m for m in self.messages if m["role"] != "system"]

    def load_history(self, messages: list[dict]) -> None:
        """Preload saved turns, e.g. after a restart (Phase 22).

        Accepts the message dicts returned by `Database.load_messages`
        (which include ``role``/``content``). Only ``user`` and
        ``assistant`` turns are restored - internal agent-loop steps and
        the system prompt are not.
        """
        for message in messages or []:
            role = message.get("role")
            content = message.get("content")
            if role in ("user", "assistant") and content:
                self.messages.append({"role": role, "content": content})
        self._trim()

    def __len__(self) -> int:
        return len(self.messages)
