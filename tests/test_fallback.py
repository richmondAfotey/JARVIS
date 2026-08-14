"""Tests for free-provider failover (AI_PROVIDER=auto)."""

from ai.brain import Brain, build_provider
from ai.providers.base import BaseProvider, ProviderError
from ai.providers.fallback import FallbackProvider
from ai.providers.local_echo import LocalEchoProvider
from ai.providers.openai_compat import OpenAICompatibleProvider


class BoomProvider(BaseProvider):
    name = "boom"

    def chat(self, messages, on_token=None):
        raise ProviderError("rate limit")


class OkProvider(BaseProvider):
    name = "ok"

    def chat(self, messages, on_token=None):
        if on_token:
            on_token("fine")
        return "fine"


# -- FallbackProvider -----------------------------------------------------

def test_fallback_uses_next_provider_when_first_fails():
    provider = FallbackProvider([BoomProvider(), OkProvider()])
    assert provider.chat([{}]) == "fine"


def test_fallback_streams_from_working_provider():
    provider = FallbackProvider([BoomProvider(), OkProvider()])
    received = []
    assert provider.chat([{}], on_token=received.append) == "fine"
    assert "".join(received) == "fine"


def test_fallback_all_fail_raises():
    provider = FallbackProvider([BoomProvider(), BoomProvider()])
    try:
        provider.chat([{}])
    except ProviderError as exc:
        message = str(exc)
        assert "All AI providers" in message
        assert "GOOGLE_API_KEY" in message  # helpful recovery hint
        return
    raise AssertionError("Expected ProviderError")


def test_fallback_empty_raises():
    try:
        FallbackProvider([])
    except ProviderError:
        return
    raise AssertionError("Expected ProviderError")


def test_fallback_is_online_reflects_children():
    assert FallbackProvider([OkProvider()]).is_online is True
    assert FallbackProvider([LocalEchoProvider()]).is_online is False


def test_is_online_flag():
    assert OkProvider().is_online is True
    assert LocalEchoProvider().is_online is False


# -- build_provider -------------------------------------------------------

class _FakeSettings:
    def __init__(self, **kw):
        defaults = {
            "ai_provider": "auto",
            "openai_api_key": "",
            "openai_model": "gpt-4o-mini",
            "openai_base_url": "",
            "anthropic_api_key": "",
            "anthropic_model": "",
            "local_model_path": "",
            "local_llm_url": "http://localhost:11434/v1",
            "local_llm_model": "llama3.1",
            "google_api_key": "",
            "google_model": "gemini-2.0-flash",
            "groq_api_key": "",
            "groq_model": "llama-3.3-70b-versatile",
            "huggingface_api_key": "",
            "huggingface_model": "meta-llama/Llama-3.3-70B-Instruct",
            "cerebras_api_key": "",
            "cerebras_model": "gpt-oss-120b",
            "openrouter_models": [],
        }
        defaults.update(kw)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_auto_with_no_keys_falls_back_to_local():
    provider = build_provider(_FakeSettings())
    assert isinstance(provider, LocalEchoProvider)


def test_auto_chains_openrouter_free_models():
    settings = _FakeSettings(
        openai_api_key="sk-or-v1-abc",
        openai_base_url="https://openrouter.ai/api/v1",
        openrouter_models=["m1:free", "m2:free"],
    )
    provider = build_provider(settings)
    assert isinstance(provider, FallbackProvider)
    assert [p.model for p in provider.providers] == ["m1:free", "m2:free"]
    assert provider.is_online is True


def test_auto_ignores_openrouter_rotation_for_plain_openai():
    settings = _FakeSettings(
        openai_api_key="sk-abc",
        openai_base_url="",
        openai_model="gpt-4o-mini",
    )
    provider = build_provider(settings)
    assert isinstance(provider, FallbackProvider)
    assert provider.providers[0].model == "gpt-4o-mini"


def test_auto_chains_free_compat_providers():
    settings = _FakeSettings(
        google_api_key="gkey",
        groq_api_key="qkey",
        huggingface_api_key="hkey",
    )
    provider = build_provider(settings)
    assert isinstance(provider, FallbackProvider)
    names = [p.name for p in provider.providers]
    assert names == ["google", "groq", "huggingface"]
    assert all(isinstance(p, OpenAICompatibleProvider) for p in provider.providers)


def test_auto_priority_order_is_openrouter_then_free():
    settings = _FakeSettings(
        openai_api_key="sk-or-v1-abc",
        openai_base_url="https://openrouter.ai/api/v1",
        openrouter_models=["m:free"],
        google_api_key="gkey",
    )
    provider = build_provider(settings)
    assert isinstance(provider, FallbackProvider)
    names = [p.name for p in provider.providers]
    assert names[0] == "openai"
    assert names[1] == "google"


def test_single_free_provider_build():
    provider = build_provider(_FakeSettings(ai_provider="google", google_api_key="gkey"))
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "google"


def test_local_provider_build():
    provider = build_provider(_FakeSettings(ai_provider="local"))
    assert isinstance(provider, LocalEchoProvider)


def test_localllm_provider_build():
    from ai.providers.local_llm import LocalLlmProvider

    provider = build_provider(
        _FakeSettings(
            ai_provider="localllm",
            local_llm_url="http://localhost:11434/v1",
            local_llm_model="dolphin-llama3",
        )
    )
    assert isinstance(provider, LocalLlmProvider)
    assert provider.model == "dolphin-llama3"
    assert str(provider.client.base_url).rstrip("/") == "http://localhost:11434/v1"


def test_localllm_friendly_error_server_down():
    from ai.providers.local_llm import LocalLlmProvider

    provider = LocalLlmProvider(model="llama3.1")
    msg = provider._friendly_error(ConnectionError("Connection refused"))
    assert "local model server" in msg


def test_localllm_requires_no_api_key():
    from ai.providers.local_llm import LocalLlmProvider

    provider = LocalLlmProvider(model="llama3.1", base_url="http://127.0.0.1:9999/v1")
    assert provider.model == "llama3.1"
    # local servers never check the key; it must be a non-empty placeholder
    assert provider.client.api_key == "local"


# -- Brain integration ----------------------------------------------------

def test_brain_is_online_with_fallback():
    brain = Brain(provider=FallbackProvider([OkProvider()]))
    assert brain.is_online is True


def test_brain_respond_falls_back_transparently():
    brain = Brain(provider=FallbackProvider([BoomProvider(), OkProvider()]))
    assert brain.respond("hi") == "fine"
