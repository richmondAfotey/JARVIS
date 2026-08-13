"""
JARVIS AI - Central configuration.

This module loads configuration from two places (in order of priority):
    1. Environment variables (OS level, e.g. a CI server).
    2. The ".env" file next to this project.

All other modules import settings from here instead of reading
environment variables themselves. That keeps configuration in one place.

Why use python-dotenv?
    It lets us keep secrets in a ".env" file that is NOT committed to
    source control. The ".env.example" file shows which variables exist.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of this file's directory.
PROJECT_ROOT = Path(__file__).resolve().parent


def _default_data_dir() -> Path:
    """Where JARVIS keeps its data (chat history, notes, memories).

    * Windows: ``%USERPROFILE%\\.jarvis-ai``
    * elsewhere: the project ``data/`` folder.
    """
    if getattr(sys, "frozen", False):
        # Running from a PyInstaller bundle - never write into it.
        home = Path.home()
        return (home / ".jarvis-ai") if home else PROJECT_ROOT / "data"
    return PROJECT_ROOT / "data"


def _env_file_location() -> Path:
    """The ``.env`` file that should back this process.

    When frozen, users place ``.env`` next to the executable; in source
    checkouts it lives at the project root.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        return exe_dir / ".env"
    return PROJECT_ROOT / ".env"


# Load variables from ".env" into the environment (does not overwrite
# variables that already exist in the OS environment).
load_dotenv(_env_file_location())


def _env(name: str, default: str = "") -> str:
    """Read an environment variable, returning a stripped value."""
    value = os.environ.get(name, default)
    return value.strip()


@dataclass
class Settings:
    """Typed access to every setting the application uses."""

    # --- Application ---
    app_name: str = "JARVIS AI"
    version: str = "1.0.0"
    data_dir: Path = field(default_factory=Path)
    update_manifest_url: str = ""

    # --- AI provider ---
    ai_provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    local_model_path: str = ""
    # Local LLM (Phase 25): an OpenAI-compatible server you run yourself
    # (Ollama / LM Studio / llama.cpp). No API key or internet needed, and
    # the model you pick decides what it answers.
    local_llm_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "llama3.1"

    # --- Free-tier providers (OpenAI-compatible, no credit card) ---
    # `auto` chains every provider below that has a key, trying the next
    # one when the previous is rate-limited.
    google_api_key: str = ""
    google_model: str = "gemini-flash-latest"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    huggingface_api_key: str = ""
    huggingface_model: str = "meta-llama/Llama-3.3-70B-Instruct"
    openrouter_models: list[str] = field(default_factory=list)

    # --- Tools (Phase 6) ---
    tools_enabled: bool = True
    tool_max_iterations: int = 4
    # Phase 28: seconds between security-threat scans (min 5). The scan
    # only observes and reports; it never acts on findings.
    threat_scan_interval: int = 60
    # Phase 25: when True, JARVIS does not pause for approval before
    # sensitive tools (screenshots, writing files, opening apps/URLs...) and
    # the "ask permission" prompt rules are omitted. Defaults to False and
    # can be changed at runtime from Settings. Behaviour stays local to the
    # user's own machine.
    unrestricted_mode: bool = False

    # --- Task scripts (Phase 15) ---
    script_max_steps: int = 30

    # --- Voice ---
    tts_engine: str = "system"
    tts_voice: str = ""
    tts_speed: int = 180
    tts_enabled: bool = True
    stt_provider: str = "google"
    stt_language: str = "en-US"
    wake_word: str = "hey jarvis"
    wake_word_enabled: bool = False
    # Phase 29: analyse the tone of spoken audio (happy/sad/angry/neutral)
    # so JARVIS can respond empathetically. Local + free (numpy only).
    tone_emotion_enabled: bool = True
    # Phase 30: let JARVIS's speaking style reflect the mood it detected.
    tts_mood_emphasis: bool = True
    # Push-to-talk: hold a hotkey to talk (optional 'keyboard' library).
    ptt_enabled: bool = False
    ptt_hotkey: str = "ctrl+space"

    # --- Local RAG (Phase 30) ---
    # Where document indexes are cached (defaults to <data_dir>/rag_index).
    rag_index_dir: str = ""
    # Where third-party plugin tools live (defaults to <project>/plugins).
    plugins_dir: str = ""

    # --- Uploads (Phase 32) ---
    # Where uploaded/pasted images and documents are stored before they are
    # analysed (defaults to <data_dir>/uploads).
    uploads_dir: str = ""

    # --- Email assistant (Phase 30) ---
    email_imap_host: str = ""
    email_smtp_host: str = ""
    email_user: str = ""
    email_password: str = ""
    email_folder: str = "INBOX"
    email_max_results: int = 10

    # --- Focus-aware recap (Phase 30) ---
    focus_recap_enabled: bool = False
    focus_recap_idle_minutes: int = 15

    # --- Folder watcher (Phase 30) ---
    # Absolute path to watch; empty = disabled. New/modified files are
    # surfaced in chat (and optionally indexed into the local RAG index).
    watch_folder: str = ""
    watch_index_changes: bool = False

    # --- Conversation summaries (Phase 30) ---
    # When a conversation grows past this many messages, old turns are
    # compressed into a summary the brain keeps in context.
    summary_threshold: int = 24
    summary_enabled: bool = True

    # --- Morning briefing (Phase 30) ---
    briefing_on_start: bool = False

    # --- Camera fall detection (Phase 31) ---
    # Always-on camera + pose-based fall detection. Starts when the app
    # opens; fall triggers a countdown, then an alert + call for help.
    camera_fall_enabled: bool = True
    camera_fall_index: int = 0
    camera_models_dir: str = ""
    # Emergency contact for fall alerts (message + call).
    fall_emergency_number: str = ""
    fall_emergency_email: str = ""
    fall_alert_message: str = "HELP - I have fallen and cannot get up."
    # Seconds the user has to cancel a false alarm before help is alerted.
    fall_countdown_seconds: int = 15

    # --- Web search / weather ---
    tavily_api_key: str = ""
    openweathermap_api_key: str = ""

    # --- Smart glasses / wearables (Phase 33) ---
    # Universal BLE/wearable interface: JARVIS can scan for paired devices,
    # pick a pair of smart glasses, and push notifications / spoken replies
    # to them. Set GLASSES_DEVICE to a name fragment to auto-select one.
    glasses_enabled: bool = True
    glasses_device: str = ""
    glasses_mirror_replies: bool = False

    # --- Misc ---
    assistant_name: str = "JARVIS"

    @classmethod
    def from_env(cls) -> "Settings":
        """Build Settings from the current environment + .env file."""
        data_dir_raw = _env("JARVIS_DATA_DIR")
        data_dir = Path(data_dir_raw) if data_dir_raw else _default_data_dir()

        return cls(
            data_dir=data_dir,
            update_manifest_url=_env("UPDATE_MANIFEST_URL"),
            ai_provider=_env("AI_PROVIDER", "openai"),
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OPENAI_MODEL", "gpt-4o-mini"),
            openai_base_url=_env("OPENAI_BASE_URL"),
            anthropic_api_key=_env("ANTHROPIC_API_KEY"),
            anthropic_model=_env("ANTHROPIC_MODEL"),
            local_model_path=_env("LOCAL_MODEL_PATH"),
            local_llm_url=_env("LOCAL_LLM_URL", "http://localhost:11434/v1"),
            local_llm_model=_env("LOCAL_LLM_MODEL", "llama3.1"),
            google_api_key=_env("GOOGLE_API_KEY"),
            google_model=_env("GOOGLE_MODEL", "gemini-flash-latest"),
            groq_api_key=_env("GROQ_API_KEY"),
            groq_model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
            huggingface_api_key=_env("HUGGINGFACE_API_KEY"),
            huggingface_model=_env(
                "HUGGINGFACE_MODEL", "meta-llama/Llama-3.3-70B-Instruct"
            ),
            openrouter_models=[
                m.strip()
                for m in _env(
                    "OPENROUTER_MODELS",
                    "nvidia/nemotron-3.5-lightning:free,"
                    "nvidia/nemotron-3-super-120b-a12b:free,"
                    "nvidia/nemotron-3-nano-30b-a3b:free",
                ).split(",")
                if m.strip()
            ],
            tools_enabled=_env("TOOLS_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
            tool_max_iterations=int(_env("TOOL_MAX_ITERATIONS", "4")),
            threat_scan_interval=int(_env("THREAT_SCAN_INTERVAL", "60")),
            unrestricted_mode=_env("UNRESTRICTED_MODE", "false").lower()
            in ("1", "true", "yes", "on"),
            script_max_steps=int(_env("SCRIPT_MAX_STEPS", "30")),
            tts_engine=_env("TTS_ENGINE", "system"),
            tts_voice=_env("TTS_VOICE"),
            tts_speed=int(_env("TTS_SPEED", "180")),
            tts_enabled=_env("TTS_ENABLED", "true").lower() in ("1", "true", "yes", "on"),
            stt_provider=_env("STT_PROVIDER", "google"),
            stt_language=_env("STT_LANGUAGE", "en-US"),
            wake_word=_env("WAKE_WORD", "hey jarvis"),
            wake_word_enabled=_env("WAKE_WORD_ENABLED", "false").lower() in ("1", "true", "yes", "on"),
            tone_emotion_enabled=_env("TONE_EMOTION_ENABLED", "true").lower()
            in ("1", "true", "yes", "on"),
            tts_mood_emphasis=_env("TTS_MOOD_EMPHASIS", "true").lower()
            in ("1", "true", "yes", "on"),
            ptt_enabled=_env("PTT_ENABLED", "false").lower() in ("1", "true", "yes", "on"),
            ptt_hotkey=_env("PTT_HOTKEY", "ctrl+space"),
            rag_index_dir=_env("RAG_INDEX_DIR"),
            plugins_dir=_env("PLUGINS_DIR"),
            uploads_dir=_env("UPLOADS_DIR"),
            email_imap_host=_env("EMAIL_IMAP_HOST"),
            email_smtp_host=_env("EMAIL_SMTP_HOST"),
            email_user=_env("EMAIL_USER"),
            email_password=_env("EMAIL_PASSWORD"),
            email_folder=_env("EMAIL_FOLDER", "INBOX"),
            email_max_results=int(_env("EMAIL_MAX_RESULTS", "10")),
            focus_recap_enabled=_env("FOCUS_RECAP_ENABLED", "false").lower()
            in ("1", "true", "yes", "on"),
            focus_recap_idle_minutes=int(_env("FOCUS_RECAP_IDLE_MINUTES", "15")),
            watch_folder=_env("WATCH_FOLDER"),
            watch_index_changes=_env("WATCH_INDEX_CHANGES", "false").lower()
            in ("1", "true", "yes", "on"),
            summary_threshold=int(_env("SUMMARY_THRESHOLD", "24")),
            summary_enabled=_env("SUMMARY_ENABLED", "true").lower()
            in ("1", "true", "yes", "on"),
            briefing_on_start=_env("BRIEFING_ON_START", "false").lower()
            in ("1", "true", "yes", "on"),
            camera_fall_enabled=_env("CAMERA_FALL_ENABLED", "true").lower()
            in ("1", "true", "yes", "on"),
            camera_fall_index=int(_env("CAMERA_FALL_INDEX", "0")),
            camera_models_dir=_env("CAMERA_MODELS_DIR"),
            fall_emergency_number=_env("FALL_EMERGENCY_NUMBER"),
            fall_emergency_email=_env("FALL_EMERGENCY_EMAIL"),
            fall_alert_message=_env(
                "FALL_ALERT_MESSAGE",
                "HELP - I have fallen and cannot get up.",
            ),
            fall_countdown_seconds=int(_env("FALL_COUNTDOWN_SECONDS", "15")),
            tavily_api_key=_env("TAVILY_API_KEY"),
            openweathermap_api_key=_env("OPENWEATHERMAP_API_KEY"),
            glasses_enabled=_env("GLASSES_ENABLED", "true").lower()
            in ("1", "true", "yes", "on"),
            glasses_device=_env("GLASSES_DEVICE"),
            glasses_mirror_replies=_env("GLASSES_MIRROR_REPLIES", "false").lower()
            in ("1", "true", "yes", "on"),
            assistant_name=_env("ASSISTANT_NAME", "JARVIS"),
        )


# A single shared settings instance used across the whole application.
# Modules do:  from config import settings
settings = Settings.from_env()


def ensure_directories() -> None:
    """Create the folders the application needs (data, logs)."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "database").mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
