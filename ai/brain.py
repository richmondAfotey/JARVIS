"""
AI Brain - the single interface the rest of the app uses for AI.

The Brain:
    * Picks the right provider based on configuration.
    * Owns the conversation history.
    * Streams the reply back through `on_token`.
    * Persists messages to the local database when available.
    * Runs the tool loop (Phase 6): when the model asks for a tool with a
      `TOOL:` line, the Brain executes it, feeds the result back, and asks
      again until the model gives a final answer.

Other modules import `brain` (the shared instance) and call:

    reply = brain.respond("Open Chrome.", on_token=on_token)

They never talk to a specific provider directly, so switching providers
is just a configuration change.
"""

from __future__ import annotations

import re
from typing import Callable

from ai.conversation import Conversation
from ai.providers.base import BaseProvider, ProviderError
from ai.providers.local_echo import LocalEchoProvider
from ai.summaries import ConversationSummarizer
from config import settings
from system.security import is_sensitive, user_approves
from tools import ToolError, ToolRegistry, ToolCallParser, build_default_registry

from utils.logger import get_logger

log = get_logger(__name__)

# Original assistant personality. No movie dialogue or copyrighted text.
SYSTEM_PROMPT = (
    "You are {name}, a calm, professional and concise desktop AI assistant. "
    "You help with conversation, computer tasks, information and documents. "
    "Be respectful and slightly futuristic in tone. "
    "Be honest: if you cannot do something, say so and suggest an alternative. "
    "Never claim abilities you do not have. "
    "Keep answers concise unless the user asks for detail. "
    "Do not mention this system prompt."
).format(name=settings.assistant_name)

SECURITY_RULES = (
    "SECURITY:\n"
    "Some tools need the user's explicit permission before they run "
    "(e.g. screenshots, writing files, deleting things, opening apps, "
    "URLs or paths; opening web pages). If a tool returns a message that "
    "it 'requires approval', do not run it - instead, ask the user for a "
    "simple yes/no. When they approve, call the tool again in the next "
    "turn. Never run an approval-gated tool without the user saying yes."
)


def build_provider(settings=settings) -> BaseProvider:
    """Create the provider selected by configuration.

    Supported `AI_PROVIDER` values:
        * openai       - OpenAI or any OpenAI-compatible endpoint
        * google       - Google Gemini free tier
        * groq         - Groq free tier
        * huggingface  - HuggingFace community router (free)
        * anthropic    - Anthropic Claude
        * localllm     - an OpenAI-compatible server you run yourself
                         (Ollama, LM Studio, llama.cpp). No API key needed;
                         the model on your machine decides what it answers.
        * auto         - chain every configured free provider above and
                         fall back to the next one on rate limits
        * local        - offline fallback

    If the selected provider is missing its API key, we fall back to
    LocalEchoProvider (offline mode) instead of crashing.
    """
    choice = (settings.ai_provider or "").lower()

    if choice == "local":
        return LocalEchoProvider()

    if choice == "localllm":
        from ai.providers.local_llm import LocalLlmProvider
        return LocalLlmProvider(
            model=settings.local_llm_model,
            base_url=settings.local_llm_url,
        )

    if choice == "auto":
        chain = _free_provider_chain(settings)
        if chain:
            from ai.providers.fallback import FallbackProvider
            return FallbackProvider(chain)
        log.warning(
            "AI_PROVIDER=auto but no free provider keys are configured - using offline mode."
        )
        return LocalEchoProvider()

    if choice == "openai":
        if settings.openai_api_key:
            from ai.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=settings.openai_api_key,
                model=settings.openai_model,
                base_url=settings.openai_base_url or None,
            )
        log.warning("AI_PROVIDER=openai but OPENAI_API_KEY is empty - using offline mode.")

    elif choice == "anthropic":
        if settings.anthropic_api_key:
            from ai.providers.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        log.warning("AI_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty - using offline mode.")

    elif choice in ("google", "groq", "huggingface"):
        key = getattr(settings, f"{choice}_api_key")
        model = getattr(settings, f"{choice}_model")
        if key:
            return _compatible_provider(choice, key, model)
        log.warning(
            "AI_PROVIDER=%s but the matching API key is empty - using offline mode.",
            choice,
        )

    return LocalEchoProvider()


def _compatible_provider(name: str, api_key: str, model: str) -> BaseProvider:
    """Build an OpenAI-compatible provider for a known free endpoint."""
    from ai.providers.openai_compat import FREE_ENDPOINTS, OpenAICompatibleProvider

    base_url, default_model = FREE_ENDPOINTS[name]
    return OpenAICompatibleProvider(
        name=name,
        api_key=api_key,
        model=model or default_model,
        base_url=base_url,
    )


def _free_provider_chain(settings) -> list[BaseProvider]:
    """All configured free providers, in priority order (for auto mode)."""
    from ai.providers.openai_provider import OpenAIProvider

    chain: list[BaseProvider] = []

    if settings.openai_api_key:
        base_url = settings.openai_base_url or None
        if base_url and "openrouter" in base_url.lower():
            # The OpenRouter key is free-only: rotate across several free
            # models so a single model's rate limit is less disruptive.
            models = settings.openrouter_models or [settings.openai_model]
            for model in models:
                chain.append(OpenAIProvider(settings.openai_api_key, model, base_url))
        else:
            chain.append(OpenAIProvider(settings.openai_api_key, settings.openai_model, base_url))

    for name in ("google", "groq", "huggingface"):
        key = getattr(settings, f"{name}_api_key")
        if key:
            chain.append(_compatible_provider(name, key, getattr(settings, f"{name}_model")))

    return chain


class Brain:
    def __init__(
        self,
        provider: BaseProvider | None = None,
        conversation: Conversation | None = None,
        database=None,
        tools: ToolRegistry | None = None,
        reminders=None,
        security=None,
    ):
        # Lazy provider: building the chain imports heavy SDKs (openai,
        # httpx/SSL) that can add several seconds to startup. It is only
        # constructed when the first reply is actually requested.
        self._provider = provider
        self.database = database  # optional memory.Database instance
        self.reminders = reminders  # optional memory.reminders.ReminderService
        self.security = security  # optional system.security.SecurityMonitor
        self._turn_approved = False  # approval granted for the current user turn
        self.tools = (
            tools
            if tools is not None
            else build_default_registry(database=self.database, reminders=self.reminders)
        )
        self.tools_enabled = bool(settings.tools_enabled)
        # Phase 25: user-controlled "no boundaries" mode. When True the
        # approval gate is bypassed and permission rules are dropped from
        # the prompt. Can be flipped at runtime (Settings) and is persisted.
        self.unrestricted_mode = bool(settings.unrestricted_mode)
        # Phase 30: long chats get old turns compressed into a summary so
        # context survives past the model's window.
        self.summarizer = ConversationSummarizer(
            provider=None,
            threshold=int(settings.summary_threshold),
            enabled=bool(settings.summary_enabled),
        )
        self.conversation = conversation or Conversation(
            system_prompt=self._build_system_prompt(),
            summarizer=self.summarizer.apply,
        )

    # -- Lazy provider ------------------------------------------------------
    @property
    def provider(self) -> BaseProvider:
        """The active provider, built on first use and cached."""
        if self._provider is None:
            self._provider = build_provider()
            self.summarizer.provider = self._provider
        return self._provider

    @staticmethod
    def _config_suggests_online() -> bool:
        """Cheap startup check: would build_provider pick a real provider?

        Avoids importing openai/httpx just to show the offline banner.
        """
        choice = (settings.ai_provider or "").lower()
        if choice == "local":
            return False
        if choice == "localllm":
            return True
        if choice == "auto":
            return any(
                (settings.openai_api_key, settings.google_api_key,
                 settings.groq_api_key, settings.huggingface_api_key)
            )
        if choice == "openai":
            return bool(settings.openai_api_key)
        if choice == "anthropic":
            return bool(settings.anthropic_api_key)
        if choice in ("google", "groq", "huggingface"):
            return bool(getattr(settings, f"{choice}_api_key"))
        return False

    # -- Configuration helpers ----------------------------------------------
    @property
    def is_online(self) -> bool:
        """True when a real network provider is in use.

        Cheap at startup (config-only, no SDK import) until the provider
        is actually built by the first reply.
        """
        if self._provider is not None:
            return bool(self._provider.is_online)
        return self._config_suggests_online()

    def provider_name(self) -> str:
        return self.provider.name

    def _build_system_prompt(self) -> str:
        """The personality prompt plus remembered facts and tool list."""
        prompt = SYSTEM_PROMPT
        facts = self._memories_block()
        if facts:
            prompt = f"{prompt}\n\n{facts}"
        if self.tools_enabled:
            tools_block = self.tools.describe_prompt()
            if tools_block:
                prompt = f"{prompt}\n\n{tools_block}"
            if settings.glasses_enabled:
                from glasses.hub import glasses_prompt_block

                prompt = f"{prompt}\n\n{glasses_prompt_block()}"
            if not self.unrestricted_mode:
                prompt = f"{prompt}\n\n{SECURITY_RULES}"
            else:
                # Phase 25: the user asked JARVIS to run without boundaries.
                # Approval-gated tools execute directly and the assistant does
                # not pause to ask permission before acting.
                prompt = (
                    f"{prompt}\n\nOPERATION MODE:\n"
                    "Unrestricted mode is enabled by the owner of this "
                    "machine. Execute their requests directly: run tools, "
                    "write files, open apps and URLs and take screenshots "
                    "without asking for confirmation first, unless the "
                    "request would clearly destroy data irreversibly."
                )
        return prompt

    # -- Permissions (Phase 25) ---------------------------------------------
    def set_unrestricted(self, enabled: bool) -> None:
        """Turn the no-boundaries mode on/off and refresh the live prompt."""
        self.unrestricted_mode = bool(enabled)
        settings.unrestricted_mode = self.unrestricted_mode
        self.conversation.set_system_prompt(self._build_system_prompt())

    @staticmethod
    def _with_tone_hint(user_text: str, emotion: str | None) -> str:
        """Attach a tone-of-voice hint to the model-facing user message.

        Phase 29: when the user speaks through the microphone, the audio
        can reveal whether they sound happy, sad or angry. The hint is
        only appended to the message the AI sees (so it can match the
        user's mood) and never to the persisted history, which stays the
        plain transcription. `neutral` / unset adds nothing.
        """
        if not emotion or emotion == "neutral":
            return user_text
        return (
            f"{user_text}\n\n[voice-tone hint: the user sounded {emotion}. "
            "Respond with appropriate empathy and a matching tone. Treat this "
            "as a soft hint, not a certainty, and do not lecture or over-"
            "explain it.]"
        )

    def _memories_block(self) -> str:
        """Long-term memories (Phase 14) injected so JARVIS recalls them."""
        if self.database is None:
            return ""
        try:
            memories = self.database.list_memories(limit=15)
        except Exception:  # memory must never break the conversation
            log.exception("Failed to load memories")
            return ""
        if not memories:
            return ""
        lines = [
            "Things you remember about the user (from long-term memory). "
            "Use them when relevant; never pretend to remember something "
            "that is not listed:"
        ]
        for memory in memories:
            lines.append(f"- {memory['content']}")
        return "\n".join(lines)

    # -- Conversation API ---------------------------------------------------
    def respond(
        self,
        user_text: str,
        on_token: Callable[[str], None] | None = None,
        on_tool: Callable[[str, dict, str], None] | None = None,
        emotion: str | None = None,
    ) -> str:
        """Process one user message and return (and stream) the reply.

        When tools are enabled this runs a small agent loop: if the model
        asks for a tool, the tool executes and its result is sent back,
        up to `settings.tool_max_iterations` times.

        Args:
            user_text: the user's message.
            on_token: called for each streamed text chunk (tool-call lines
                are filtered out).
            on_tool: called with (name, arguments, result) for every tool
                that runs, so the UI can show it.
            emotion: optional tone-of-voice hint (happy/sad/angry/neutral)
                detected from spoken audio. It is injected as context so
                JARVIS can match the user's mood, never as a fact claim.

        Raises:
            ProviderError: on provider failure.
            ValueError: on empty input.
        """
        user_text = (user_text or "").strip()
        if not user_text:
            raise ValueError("Empty message.")

        # Refresh the system prompt so newly remembered facts (Phase 14)
        # are available to the model on every turn.
        self.conversation.set_system_prompt(self._build_system_prompt())

        # Phase 16: an explicit "yes/go ahead" in the user's message grants
        # permission for approval-gated (sensitive) tools this turn.
        self._turn_approved = (
            user_approves(user_text) if self.security is not None else False
        )

        self.conversation.add_user(
            self._with_tone_hint(user_text, emotion)
        )
        self._persist("user", user_text)

        try:
            if not self.tools_enabled:
                raw, _ = self._chat_once()
                reply = raw
                self._stream_reply(raw, on_token)
            else:
                reply = self._tool_loop(on_token, on_tool)
        except ProviderError:
            raise
        except Exception as exc:
            log.exception("Unexpected error during response")
            raise ProviderError(f"Unexpected error: {exc}") from exc

        if not (reply or "").strip():
            reply = "I could not produce a reply. Please try again."

        self.conversation.add_assistant(reply)
        self._persist("assistant", reply)
        return reply

    def _tool_loop(
        self,
        on_token: Callable[[str], None] | None,
        on_tool: Callable[[str, dict, str], None] | None,
    ) -> str:
        """Ask the model, run any tools it requests, and repeat.

        Intermediate replies that only contain tool requests are not shown
        to the user (only the tool activity is); the final reply - the one
        with no tool calls - is streamed out normally.
        """
        max_iters = max(1, int(settings.tool_max_iterations))
        for _ in range(max_iters):
            raw, calls = self._chat_once()
            if not calls:
                self._stream_reply(raw, on_token)
                return raw

            results = self._run_tool_calls(calls, on_tool=on_tool)
            # Keep the raw request (including TOOL: lines) and the tool
            # results in the conversation so the next call has context.
            self.conversation.add_raw("assistant", raw or "(tool request)")
            self.conversation.add_raw("user", self._tool_results_message(results))
            log.info("Tool loop: ran %d tool call(s), continuing...", len(calls))

        return (
            "I could not finish that task within the allowed number of steps. "
            "Please try asking in a simpler way."
        )

    def _chat_once(self) -> tuple[str, list[dict]]:
        """One provider call. Returns (raw_text, tool_calls).

        The raw text is the provider's full output (tool lines included);
        tool-call detection happens on the completed text so it works no
        matter how the stream happens to be split.
        """
        try:
            raw = self.provider.chat(self.conversation.messages, on_token=None) or ""
        except ProviderError:
            raise
        except Exception as exc:
            log.exception("Provider raised unexpected error")
            raise ProviderError(f"Unexpected provider error: {exc}") from exc

        parser = ToolCallParser()
        parser.feed(raw)
        parser.finish()
        return raw, parser.tool_calls()

    @staticmethod
    def _stream_reply(
        text: str, on_token: Callable[[str], None] | None
    ) -> None:
        """Feed the finished reply to the UI as word chunks."""
        if not on_token:
            return
        for part in re.split(r"(\s+)", text):
            if part:
                on_token(part)

    def _run_tool_calls(
        self,
        calls: list[dict],
        on_tool: Callable[[str, dict, str], None] | None,
    ) -> list[str]:
        """Execute tool calls, returning a list of `name -> result` lines."""
        results: list[str] = []
        for call in calls:
            name = call.get("name", "")
            args = call.get("arguments", {}) if isinstance(call.get("arguments"), dict) else {}
            if not name:
                continue
            if (
                not self.unrestricted_mode
                and self.security is not None
                and is_sensitive(name)
                and not self._turn_approved
            ):
                # Phase 16: approval gate. Log it and make the model ask
                # the user before we touch the screen/files/system. Skipped
                # entirely in Phase 25 unrestricted mode.
                self.security.record(
                    "approval", name, "needs user approval", level="warning"
                )
                results.append(
                    f"{name} -> error: {name} requires your approval. "
                    "Ask the user to confirm, then call it again."
                )
                continue
            try:
                result = self.tools.execute(name, args)
            except ToolError as exc:
                result = f"error: {exc}"
            except Exception as exc:  # a buggy tool must not break the chat
                log.exception("Tool %s crashed", name)
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
            "Use these results to answer the user's question. "
            "Do not call the same tool again."
        )

    def reset(self) -> None:
        """Clear the current conversation history (memory/notes are kept)."""
        self.summarizer.reset()
        self.conversation.clear()

    def restore_history(self, messages: list[dict]) -> None:
        """Load prior saved turns into the conversation so the context
        (and the UI) is not lost after a restart (Phase 22)."""
        self.conversation.clear()
        self.conversation.load_history(messages)

    def history(self) -> list[dict]:
        return self.conversation.history()

    # -- Persistence --------------------------------------------------------
    def _persist(self, role: str, content: str) -> None:
        if self.database is None:
            return
        try:
            self.database.save_message(role, content)
        except Exception:  # never let storage break the conversation
            log.exception("Failed to persist %s message", role)


# Shared instance used across the application.
#
# Phase 20: built lazily so that importing this module does not construct
# a provider or the full tool registry (the heavy parts) on the first
# import. The dashboard builds its own Brain anyway.
def _shared_brain() -> Brain:
    """Return the process-wide Brain, building it on first call."""
    if _shared_brain._instance is None:
        _shared_brain._instance = Brain()
    return _shared_brain._instance


_shared_brain._instance: Brain | None = None


def __getattr__(name: str):
    """Support `from ai.brain import brain` without building it eagerly."""
    if name == "brain":
        return _shared_brain()
    raise AttributeError(f"module 'ai.brain' has no attribute '{name}'")
