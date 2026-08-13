"""Tests for the configuration module."""

import pytest

from config import Settings, settings, PROJECT_ROOT, ensure_directories
import config as config_module


def test_defaults_present():
    s = Settings.from_env()
    assert s.app_name == "JARVIS AI"
    assert s.assistant_name  # falls back to JARVIS


def test_frozen_data_dir_not_in_bundle(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", True, raising=False)
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    data_dir = config_module._default_data_dir()
    assert ".jarvis-ai" in str(data_dir)
    assert "dist" not in str(data_dir)


def test_unfrozen_data_dir_under_project(monkeypatch):
    monkeypatch.setattr(config_module.sys, "frozen", False, raising=False)
    monkeypatch.delenv("JARVIS_DATA_DIR", raising=False)
    assert config_module._default_data_dir() == PROJECT_ROOT / "data"


# -- environment parsing ----------------------------------------------------

def test_from_env_adopts_env_overrides(monkeypatch):
    monkeypatch.setenv("ASSISTANT_NAME", "FRIDAY")
    monkeypatch.setenv("AI_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "gkey-123")
    s = Settings.from_env()
    assert s.assistant_name == "FRIDAY"
    assert s.ai_provider == "google"
    assert s.google_api_key == "gkey-123"


def test_boolean_env_parsing(monkeypatch):
    monkeypatch.setenv("TOOLS_ENABLED", "false")
    monkeypatch.setenv("TTS_ENABLED", "1")
    monkeypatch.setenv("WAKE_WORD_ENABLED", "on")
    monkeypatch.setenv("TONE_EMOTION_ENABLED", "off")
    s = Settings.from_env()
    assert s.tools_enabled is False
    assert s.tts_enabled is True
    assert s.wake_word_enabled is True
    assert s.tone_emotion_enabled is False


def test_integer_env_parsing(monkeypatch):
    monkeypatch.setenv("TOOL_MAX_ITERATIONS", "8")
    monkeypatch.setenv("SCRIPT_MAX_STEPS", "12")
    monkeypatch.setenv("TTS_SPEED", "200")
    s = Settings.from_env()
    assert s.tool_max_iterations == 8
    assert s.script_max_steps == 12
    assert s.tts_speed == 200


def test_openrouter_models_split_and_trim(monkeypatch):
    monkeypatch.setenv(
        "OPENROUTER_MODELS",
        "nvidia/a:free, openrouter/b:free ,nvidia/c:free",
    )
    s = Settings.from_env()
    assert s.openrouter_models == ["nvidia/a:free", "openrouter/b:free", "nvidia/c:free"]


def test_openrouter_models_default(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODELS", raising=False)
    s = Settings.from_env()
    assert "nvidia/nemotron-3.5-lightning:free" in s.openrouter_models


def test_data_dir_from_env(monkeypatch):
    monkeypatch.setenv("JARVIS_DATA_DIR", str(PROJECT_ROOT / "custom_data"))
    s = Settings.from_env()
    assert s.data_dir == PROJECT_ROOT / "custom_data"


def test_data_dir_defaults_under_project():
    s = Settings.from_env()
    assert str(s.data_dir) == str(PROJECT_ROOT / "data")


def test_shared_settings_is_typed():
    assert isinstance(settings, Settings)


def test_uploads_dir_from_env(monkeypatch):
    monkeypatch.setenv("UPLOADS_DIR", "C:/my_uploads")
    assert Settings.from_env().uploads_dir == "C:/my_uploads"


def test_uploads_dir_default_empty():
    assert Settings().uploads_dir == ""


def test_ensure_directories_creates_folders(tmp_path):
    # Point Settings at a temp folder and create the dirs there.
    s = Settings()
    s.data_dir = tmp_path / "data"
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "database").mkdir(parents=True, exist_ok=True)
    (s.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
    assert (s.data_dir / "logs").is_dir()
    assert (s.data_dir / "database").is_dir()
    assert (s.data_dir / "uploads").is_dir()
