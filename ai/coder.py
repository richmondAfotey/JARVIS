"""
Coding agent (Phase 38) - a focused "software engineer" loop inside JARVIS.

Given a coding request, the agent:

    1. Builds a fresh coding conversation with a project-aware system prompt
       and a coding-tuned provider (``settings.coder_provider`` /
       ``settings.coder_model``; falls back to the main provider when the
       coding provider is not configured).
    2. Runs the same tool loop as the Brain (the ``TOOL:`` protocol) but
       over the coding toolset: repo_tree, repo_find, read_code, edit_code,
       run_tests, git_status, code_query.
    3. Emphasises the test-feedback loop: after edits it runs the tests,
       feeds failures back, and iterates until green or the iteration cap.
    4. Returns a concise summary (what changed + final test result).

Approval: invoking this agent is itself an approval-gated tool
(``coding_agent`` is in SENSITIVE_TOOLS), so the user's consent covers the
session's file edits. All the underlying repo tools are local; only the
model calls go online.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ai.conversation import Conversation
from ai.providers.base import BaseProvider, ProviderError
from config import settings
from tools.base import ToolError
from tools.registry import ToolCallParser
from tools.coding import _default_project_dir, build_coding_registry

from utils.logger import get_logger

log = get_logger(__name__)

CODING_SYSTEM_PROMPT = (
    "You are {name}'s coding engineer - an expert software developer "
    "working on the user's own codebase at {project_dir}.\n\n"
    "WORKFLOW:\n"
    "1. Before editing, explore: repo_tree to see the layout, then "
    "repo_find / read_code / code_query to read the exact code involved. "
    "Never guess what a file contains.\n"
    "2. Make minimal, surgical changes with edit_code. 'old' must match the "
    "current text exactly once - copy it verbatim from read_code.\n"
    "3. After editing, run run_tests to verify. If a test fails, read the "
    "failure, fix the root cause, and re-run. Iterate until the tests pass "
    "or you run out of steps.\n"
    "4. Finish with a concise summary: what you changed, which files, and "
    "the final test result. Keep it to a few lines.\n\n"
    "RULES:\n"
    "- Only edit files under the project. Never fabricate file contents or "
    "test results - read them with the tools.\n"
    "- Keep the user's existing style, imports and conventions. Do not add "
    "unnecessary comments.\n"
    "- The user has approved this coding session, so approval-gated tools "
    "may run directly.\n"
    "- When asked to explain code, ground the answer in the real source "
    "using the repo tools."
).format(name=settings.assistant_name, project_dir="<project>")


def build_coder_provider(settings=settings) -> BaseProvider:
    """A provider for coding work, from CODER_PROVIDER/CODER_MODEL.

    Falls back to the main provider when the coding provider is empty or
    its API key is missing.
    """
    from ai.brain import build_provider
    from ai.providers.anthropic_provider import AnthropicProvider
    from ai.providers.local_llm import LocalLlmProvider
    from ai.providers.openai_provider import OpenAIProvider

    choice = (settings.coder_provider or "").strip().lower()
    if not choice:
        return build_provider()

    if choice == "anthropic":
        if settings.anthropic_api_key:
            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                model=settings.coder_model or None,
            )
        log.warning("CODER_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty - using main provider.")

    elif choice == "openai":
        if settings.openai_api_key:
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.coder_model or settings.openai_model,
                base_url=settings.openai_base_url or None,
            )
        log.warning("CODER_PROVIDER=openai but OPENAI_API_KEY is empty - using main provider.")

    elif choice in ("google", "groq", "huggingface", "cerebras"):
        key = getattr(settings, f"{choice}_api_key")
        if key:
            from ai.brain import _compatible_provider

            return _compatible_provider(
                choice,
                key,
                settings.coder_model or "",
                default_model=getattr(settings, f"{choice}_model"),
            )
        log.warning(
            "CODER_PROVIDER=%s but the matching API key is empty - using main provider.",
            choice,
        )

    elif choice == "localllm":
        return LocalLlmProvider(
            model=settings.coder_model or settings.local_llm_model,
            base_url=settings.local_llm_url,
        )

    return build_provider()


class CodingAgent:
    """Runs one coding task to completion with a tool + test-feedback loop."""

    def __init__(
        self,
        provider: BaseProvider | None = None,
        project_dir: Path | str | None = None,
    ):
        self.project_dir = Path(project_dir) if project_dir else _default_project_dir()
        self.provider = provider or build_coder_provider()
        self.tools = build_coding_registry(self.project_dir)
        self.conversation = Conversation(
            system_prompt=CODING_SYSTEM_PROMPT.format(
                name=settings.assistant_name,
                project_dir=str(self.project_dir),
            ),
            max_messages=48,
        )

    # -- Public API ----------------------------------------------------------
    def run(
        self,
        user_text: str,
        on_token: Callable[[str], None] | None = None,
        on_tool: Callable[[str, dict, str], None] | None = None,
    ) -> str:
        """Execute one coding request and return the agent's final reply.

        The conversation is reset per call so each coding session starts
        fresh (the agent has no memory of earlier sessions).
        """
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("Empty coding request.")

        self.conversation.clear()
        self.conversation.add_user(user_text)

        max_iters = max(1, int(getattr(settings, "coder_max_iterations", 6) or 6))
        for _ in range(max_iters):
            raw, calls = self._chat_once()
            if not calls:
                if on_token:
                    for part in raw.split(" "):
                        if part:
                            on_token(part + " ")
                return raw
            results = self._run_tool_calls(calls, on_tool=on_tool)
            self.conversation.add_raw("assistant", raw or "(tool request)")
            self.conversation.add_raw("user", self._tool_results_message(results))
            log.info("Coding agent: ran %d tool call(s), continuing...", len(calls))

        return (
            "I could not finish the coding task within the allowed number of "
            "steps. The partial changes are on disk - tell me to continue or "
            "raise CODER_MAX_ITERATIONS for longer tasks."
        )

    # -- Loop internals ------------------------------------------------------
    def _chat_once(self) -> tuple[str, list[dict]]:
        try:
            raw = self.provider.chat(self.conversation.messages, on_token=None) or ""
        except ProviderError:
            raise
        except Exception as exc:
            log.exception("Coding provider raised unexpected error")
            raise ProviderError(f"Unexpected coding provider error: {exc}") from exc
        parser = ToolCallParser()
        parser.feed(raw)
        parser.finish()
        return raw, parser.tool_calls()

    def _run_tool_calls(
        self,
        calls: list[dict],
        on_tool: Callable[[str, dict, str], None] | None,
    ) -> list[str]:
        results: list[str] = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("arguments", {}) if isinstance(call.get("arguments"), dict) else {}
            if not name:
                continue
            try:
                result = self.tools.execute(name, args)
            except ToolError as exc:
                result = f"error: {exc}"
            except Exception as exc:  # a buggy tool must never break the loop
                log.exception("Coding tool %s crashed", name)
                result = f"error: {exc}"
            if on_tool:
                on_tool(name, args, result)
            results.append(f"{name} -> {result}")
        return results

    @staticmethod
    def _tool_results_message(results: list[str]) -> str:
        joined = "\n".join(results)
        return (
            "[Tool results]\n"
            f"{joined}\n\n"
            "Use these results to make progress on the task. If any edit_code "
            "succeeded, run run_tests next to verify. Do not call the same "
            "tool twice in a row with identical arguments."
        )


# Shared agent instance (reused across sessions; run() resets each one).
_shared_agent: CodingAgent | None = None


def get_coding_agent() -> CodingAgent:
    """The process-wide coding agent, built lazily."""
    global _shared_agent
    if _shared_agent is None:
        _shared_agent = CodingAgent()
    return _shared_agent
