"""
Voice confirmation tool (Phase 30).

Lets JARVIS ask for a *spoken* yes/no when a sensitive action is about to
happen (or when approval was auto-granted via a previous "yes" but the
action is important enough to double-check aloud). Uses the same
microphone + recognizer as the rest of the app through a module-level
STT provider that the dashboard sets at startup.

If no STT is wired up (headless / tests) the tool reports that it cannot
listen, so the AI can fall back to a text confirmation instead.
"""

from __future__ import annotations

import re
from typing import Callable

from tools.base import Tool, ToolError
from utils.logger import get_logger

log = get_logger(__name__)

_YES_RE = re.compile(r"\b(yes|yeah|yep|sure|go ahead|ok|okay|confirm|y)\b", re.IGNORECASE)
_NO_RE = re.compile(r"\b(no|nope|negative|don't|do not|cancel|stop)\b", re.IGNORECASE)

#: The app's shared STT instance; set by the dashboard.
_stt = None
_listen_fn: Callable[[float], str] | None = None


def wire_stt(stt, listen: Callable[[float], str] | None = None) -> None:
    """Give the confirm tool access to the live microphone.

    Args:
        stt: a `voice.speech_to_text.SpeechToText` instance (or None to
            clear). Only its resources are checked; the actual listen call
            uses `listen` when provided so the dashboard can choose between
            `listen` and `listen_with_emotion`.
        listen: optional callable ``(timeout) -> text``. Defaults to the
            STT's ``listen`` method.
    """
    global _stt, _listen_fn
    _stt = stt
    _listen_fn = listen


class ConfirmByVoiceTool(Tool):
    name = "confirm_by_voice"
    description = (
        "Ask the user to confirm something by speaking yes or no into the "
        "microphone. Returns 'confirmed' or 'declined'. Use it before an "
        "important action when you want a spoken double-check."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Short question to speak aloud, e.g. 'Should I delete the file?'",
            }
        },
        "required": [],
    }

    def execute(self, args: dict) -> str:
        prompt = (self._arg(args, "prompt") or "").strip()
        if _stt is None or (_listen_fn is None and not _stt.libraries_available):
            raise ToolError(
                "No microphone is wired up right now - ask the user to confirm "
                "by typing yes or no instead."
            )

        listen = _listen_fn or _stt.listen
        try:
            text = listen(6.0)
        except Exception as exc:  # noqa: BLE001 - a bad listen must not crash
            log.debug("Voice confirmation failed: %s", exc)
            raise ToolError(
                "Could not hear a reply - ask the user to type yes or no instead."
            ) from exc

        if not text:
            raise ToolError(
                "No reply was heard - ask the user to confirm by typing yes or no."
            )

        answer = text.strip().lower()
        if _NO_RE.search(answer) and not _YES_RE.search(answer):
            log.info("Voice confirmation declined (heard %r after %r)", answer, prompt)
            return "declined"
        if _YES_RE.search(answer):
            log.info("Voice confirmation approved (heard %r after %r)", answer, prompt)
            return "confirmed"
        log.info("Voice confirmation ambiguous (heard %r after %r)", answer, prompt)
        raise ToolError(
            f"I heard '{text}' but that is not a clear yes or no. Please confirm "
            "by speaking 'yes' or 'no', or by typing."
        )


def register_voice_confirm_tools(registry) -> None:
    registry.register(ConfirmByVoiceTool())