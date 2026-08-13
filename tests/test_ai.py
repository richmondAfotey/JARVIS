"""Tests for the AI brain, conversation manager, and offline provider."""

from ai.brain import Brain, build_provider, SYSTEM_PROMPT
from ai.conversation import Conversation
from ai.providers.base import BaseProvider, ProviderError
from ai.providers.local_echo import LocalEchoProvider
from utils.helpers import safe_eval_math, normalize_text


# -- Offline maths -----------------------------------------------------------

def test_safe_math_basic():
    assert safe_eval_math("2 + 2") == "4"


def test_safe_math_operators():
    assert safe_eval_math("10 * 4") == "40"
    assert safe_eval_math("7 - 3") == "4"
    assert safe_eval_math("10 / 4") == "2.5"
    assert safe_eval_math("2 ** 3") == "8"
    assert safe_eval_math("10 % 3") == "1"


def test_safe_math_division_by_zero():
    assert safe_eval_math("5 / 0") == ""


def test_safe_math_rejects_code():
    assert safe_eval_math("__import__('os').system('x')") == ""
    assert safe_eval_math("print('hi')") == ""


def test_safe_math_empty():
    assert safe_eval_math("not math at all") == ""


# -- LocalEchoProvider -------------------------------------------------------

def test_local_greeting():
    provider = LocalEchoProvider()
    reply = provider.chat([{"role": "user", "content": "hello"}])
    assert "offline" in reply.lower() or "hello" in reply.lower()


def test_local_time():
    provider = LocalEchoProvider()
    reply = provider.chat([{"role": "user", "content": "what time is it?"}])
    assert ":" in reply  # contains HH:MM


def test_local_math():
    provider = LocalEchoProvider()
    reply = provider.chat([{"role": "user", "content": "calculate 12 * 8"}])
    assert "96" in reply


def test_local_unknown_is_honest():
    provider = LocalEchoProvider()
    reply = provider.chat([{"role": "user", "content": "write me a poem"}])
    assert "offline" in reply.lower()


def test_local_streams_tokens():
    provider = LocalEchoProvider()
    received = []
    provider.chat([{"role": "user", "content": "what time is it?"}], on_token=received.append)
    assert len(received) > 0
    assert "".join(received).strip()  # assembled text is non-empty


# -- Conversation manager ----------------------------------------------------

def test_conversation_keeps_system_prompt():
    conv = Conversation(system_prompt="be nice")
    conv.add_user("hi")
    assert conv.messages[0] == {"role": "system", "content": "be nice"}


def test_conversation_order():
    conv = Conversation(system_prompt="s")
    conv.add_user("a")
    conv.add_assistant("b")
    conv.add_user("c")
    roles = [m["role"] for m in conv.history()]
    assert roles == ["user", "assistant", "user"]


def test_conversation_trims():
    conv = Conversation(system_prompt="s", max_messages=4)
    for i in range(10):
        conv.add_user(f"u{i}")
        conv.add_assistant(f"a{i}")
    # system prompt + at most max_messages turns
    non_system = [m for m in conv.messages if m["role"] != "system"]
    assert len(non_system) <= 4


def test_conversation_clear():
    conv = Conversation(system_prompt="s")
    conv.add_user("x")
    conv.clear()
    assert len(conv.history()) == 0
    assert conv.messages[0]["role"] == "system"


def test_conversation_add_raw_keeps_role():
    conv = Conversation(system_prompt="s")
    conv.add_raw("user", "tool result here")
    assert conv.messages[-1] == {"role": "user", "content": "tool result here"}
    # raw messages are context-only and still part of history()
    assert any(m["content"] == "tool result here" for m in conv.history())


def test_conversation_set_system_prompt_replaces():
    conv = Conversation(system_prompt="old")
    conv.add_user("hi")
    conv.set_system_prompt("new")
    assert conv.messages[0] == {"role": "system", "content": "new"}


def test_conversation_set_system_prompt_removes():
    conv = Conversation(system_prompt="")
    conv.add_user("hi")
    conv.set_system_prompt("")  # empty prompt -> no system line
    assert all(m["role"] != "system" for m in conv.messages)


def test_conversation_trim_keeps_system_first():
    conv = Conversation(system_prompt="keep me", max_messages=2)
    for i in range(6):
        conv.add_user(f"u{i}")
    assert conv.messages[0]["role"] == "system"
    assert len([m for m in conv.messages if m["role"] != "system"]) == 2
    # the most recent user messages survive the trim
    assert conv.messages[-1]["content"] == "u5"


def test_conversation_history_excludes_system():
    conv = Conversation(system_prompt="s")
    conv.add_user("a")
    conv.add_assistant("b")
    assert all(m["role"] != "system" for m in conv.history())


# -- load_history (Phase 22: restore after restart) --------------------------

def test_load_history_populates():
    conv = Conversation(system_prompt="s")
    conv.load_history(
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    )
    assert conv.history() == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    assert conv.messages[0]["role"] == "system"


def test_load_history_ignores_non_persisted_roles():
    conv = Conversation(system_prompt="s")
    conv.load_history(
        [
            {"role": "system", "content": "ignored injected prompt"},
            {"role": "user", "content": ""},  # empty content dropped
            {"role": "user", "content": "keep me"},
        ]
    )
    assert [m["content"] for m in conv.history()] == ["keep me"]


def test_load_history_trims_to_limit():
    conv = Conversation(system_prompt="s", max_messages=4)
    conv.load_history(
        [{"role": "user", "content": f"m{i}"} for i in range(20)]
    )
    assert len(conv.history()) <= 4
    # the most recent messages survive the trim
    assert conv.history()[-1]["content"] == "m19"


def test_load_history_none_and_empty_are_safe():
    conv = Conversation(system_prompt="s")
    conv.add_user("existing")
    conv.load_history(None)
    conv.load_history([])
    assert len(conv.history()) == 1


# -- normalize_text (voice phrase matching) ---------------------------------

def test_normalize_text():
    assert normalize_text("Hey, JARVIS!") == "hey jarvis"
    assert normalize_text("  Open   Chrome,  please.  ") == "open chrome please"
    assert normalize_text("What's up?") == "what's up"


# -- Brain -------------------------------------------------------------------

def test_brain_offline_without_key(monkeypatch):
    # Pretend no API keys are set -> provider must be offline.
    class Fake:
        ai_provider = "openai"
        openai_api_key = ""
        anthropic_api_key = ""
        openai_model = "gpt-4o-mini"
        anthropic_model = ""
    provider = build_provider(Fake())
    assert isinstance(provider, LocalEchoProvider)


def test_brain_respond_local():
    brain = Brain(provider=LocalEchoProvider())
    reply = brain.respond("calculate 6 * 7")
    assert "42" in reply
    assert len(brain.history()) == 2  # user + assistant


def test_brain_respond_empty_raises():
    brain = Brain(provider=LocalEchoProvider())
    try:
        brain.respond("   ")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for empty message")


def test_brain_provider_error_propagates():
    class BoomProvider(LocalEchoProvider):
        def chat(self, messages, on_token=None):
            raise ProviderError("boom")

    brain = Brain(provider=BoomProvider())
    try:
        brain.respond("hi")
    except ProviderError as exc:
        assert "boom" in str(exc)
        return
    raise AssertionError("Expected ProviderError")


def test_system_prompt_has_personality():
    assert "concise" in SYSTEM_PROMPT


# -- Brain robustness -------------------------------------------------------

class EmptyProvider(BaseProvider):
    name = "empty"

    def chat(self, messages, on_token=None):
        return "   "  # provider produced nothing


def test_brain_empty_reply_falls_back():
    brain = Brain(provider=EmptyProvider())
    reply = brain.respond("hi")
    assert "could not produce a reply" in reply


def test_brain_provider_name_and_online_flag():
    local = Brain(provider=LocalEchoProvider())
    assert local.provider_name() == "local"
    assert local.is_online is False

    class _Online(LocalEchoProvider):
        name = "remote"
        is_online = True

    online = Brain(provider=_Online())
    assert online.is_online is True


def test_brain_reset_clears_history():
    brain = Brain(provider=LocalEchoProvider(), conversation=Conversation())
    brain.respond("calculate 2 + 3")
    assert len(brain.history()) >= 2
    brain.reset()
    assert brain.history() == []


def test_tools_disabled_omits_tool_block():
    class Plain(BaseProvider):
        name = "plain"

        def chat(self, messages, on_token=None):
            return "ok"

    brain = Brain(provider=Plain(), conversation=Conversation())
    brain.tools_enabled = False
    brain.respond("hi")
    system = brain.conversation.messages[0]["content"]
    assert "TOOL:" not in system


def test_tools_enabled_includes_tools_and_security():
    from ai.brain import SECURITY_RULES

    brain = Brain(provider=LocalEchoProvider(), conversation=Conversation())
    prompt = brain._build_system_prompt()
    assert "TOOL:" in prompt
    # the security block is actually present in the assembled prompt
    assert "requires approval" in prompt.lower()
    assert "requires approval" in SECURITY_RULES.lower()


# -- Provider error message mapping -----------------------------------------

def test_openai_friendly_error_messages():
    from ai.providers.openai_provider import OpenAIProvider

    assert "API key" in OpenAIProvider._friendly_error(ProviderError("401 unauthorized"))
    assert "rate limit" in OpenAIProvider._friendly_error(ProviderError("You have hit 429 quota"))
    assert "internet" in OpenAIProvider._friendly_error(ProviderError("connection refused"))
    assert "OpenAI error" in OpenAIProvider._friendly_error(ProviderError("weird failure"))


def test_anthropic_friendly_error_messages():
    from ai.providers.anthropic_provider import AnthropicProvider

    assert "API key" in AnthropicProvider._friendly_error(ProviderError("invalid api key"))
    assert "rate limit" in AnthropicProvider._friendly_error(ProviderError("rate limit reached 429"))
    assert "internet" in AnthropicProvider._friendly_error(ProviderError("timeout connecting"))
    assert "Anthropic error" in AnthropicProvider._friendly_error(ProviderError("unknown"))
