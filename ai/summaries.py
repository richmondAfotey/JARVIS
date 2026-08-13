"""
Conversation summarization (Phase 30).

Long chats eventually exceed a model's context window. Instead of simply
dropping the oldest turns (which loses information), JARVIS compresses them
into a short summary the model keeps as a single system-style message. The
summarizer is provider-agnostic: it asks whatever chat provider is in use
to condense the oldest N user/assistant turns.

The summary itself is cached on the conversation object so it is only
rebuilt once per growth spurt, not on every turn.
"""

from __future__ import annotations

import threading

from utils.logger import get_logger

log = get_logger(__name__)

_SUMMARY_PROMPT = (
    "Summarize the following conversation turns into a short recap for "
    "another model so it can continue without reading every line. Keep:\n"
    "  * the user's key requests, preferences and decisions\n"
    "  * any facts, names, deadlines or values that were stated\n"
    "  * what was already done vs. what is still pending\n"
    "Use plain compact prose. No greetings, no preamble.\n\n"
    "CONVERSATION:\n{turns}"
)


def summarize_turns(provider, turns: list[dict], max_chars: int = 1200) -> str:
    """Ask `provider` to compress `turns` into a short summary.

    Falls back to a lossy-but-safe local digest if the provider errors or
    is the offline echo, so a summarization failure never blocks a chat.
    """
    if not turns:
        return ""
    if provider is not None and getattr(provider, "is_online", False):
        try:
            transcript = "\n".join(
                f"{t.get('role', 'user')}: {t.get('content', '')}" for t in turns
            )
            text = provider.chat(
                [{"role": "user", "content": _SUMMARY_PROMPT.format(turns=transcript)}]
            ) or ""
            text = text.strip()
            if text:
                return text[:max_chars]
        except Exception as exc:  # noqa: BLE001 - fall back to local digest
            log.debug("Provider summary failed: %s", exc)
    return _local_digest(turns)[:max_chars]


def _local_digest(turns: list[dict]) -> str:
    """A cheap, dependency-free digest for offline mode."""
    user_lines: list[str] = []
    assistant_lines: list[str] = []
    for turn in turns:
        content = (turn.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        if turn.get("role") == "user":
            user_lines.append(f"- user asked: {content[:160]}")
        elif turn.get("role") == "assistant":
            assistant_lines.append(f"- I replied: {content[:120]}")
    parts = ["Earlier in this conversation:"]
    parts.extend(user_lines[-8:])
    if assistant_lines:
        parts.append("Summary of my earlier replies: " + " ".join(assistant_lines[-6:]))
    return "\n".join(parts)


class ConversationSummarizer:
    """Compresses old turns once the history grows past a threshold."""

    def __init__(
        self,
        provider=None,
        threshold: int = 24,
        keep_recent: int = 10,
        enabled: bool = True,
    ) -> None:
        self.provider = provider
        self.threshold = int(threshold)
        self.keep_recent = int(keep_recent)
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._summary: str = ""
        self._pending = False

    @property
    def summary(self) -> str:
        return self._summary

    def apply(self, history: list[dict]) -> list[dict]:
        """Return history with old turns replaced by a summary when needed.

        ``history`` must be the full user/assistant turn list (no system
        prompt and no previously generated summary - `_trim` strips those).
        When it grows past ``threshold`` turns the oldest ``keep_recent``
        turns are replaced by one synthetic ``summary`` system message;
        while the history is shorter than the threshold again the previous
        summary is re-attached instead of dropped.
        """
        if not self.enabled or not history:
            return history
        total = len(history)
        with self._lock:
            if total <= self.threshold:
                if self._pending and self._summary:
                    return [self._summary_msg()] + history
                return history

            keep = self.keep_recent
            old = history[: total - keep]
            recent = history[total - keep :]
            if not old:
                return history
            self._summary = summarize_turns(self.provider, old)
            self._pending = bool(self._summary)
            return [self._summary_msg()] + recent

    def _summary_msg(self) -> dict:
        return {
            "role": "system",
            "content": f"[summary of earlier turns]\n{self._summary}",
        }

    def reset(self) -> None:
        with self._lock:
            self._summary = ""
            self._pending = False


_shared: ConversationSummarizer | None = None
_shared_lock = threading.Lock()


def get_shared_summarizer(provider=None) -> ConversationSummarizer:
    """A process-wide summarizer (bound to a provider on first use)."""
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = ConversationSummarizer(provider=provider)
        elif provider is not None and _shared.provider is None:
            _shared.provider = provider
        return _shared