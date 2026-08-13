"""
Text-to-speech service.

Turns JARVIS replies into spoken words using the offline Windows voices
(SAPI5, via the `pyttsx3` library). No internet and no API key required.

Design notes:
    * The engine is created lazily on first use, so the app still starts
      even on machines without a working speech engine.
    * If speech is unavailable we log the reason and return False - the
      app then simply continues in text-only mode (graceful fallback).
    * `speak()` is blocking; call it from a background thread so the UI
      never freezes. A lock prevents overlapping speech.

The engine itself is created by `_create_engine()` so tests can replace
it with a fake engine (no hardware needed).
"""

from __future__ import annotations

import threading

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)


class TTSService:
    def __init__(
        self,
        enabled: bool = True,
        rate: int = 180,
        voice_name: str = "",
        mood_emphasis: bool = True,
    ):
        self.enabled = enabled
        self.rate = rate
        self.voice_name = voice_name
        # Phase 30: when True, spoken replies are slowed slightly for
        # "sad" tone hints and sped up for a cheerful "happy" hint, so the
        # voice matches the mood JARVIS detected in the user's speech.
        self.mood_emphasis = mood_emphasis
        self._engine = None
        self._init_error: str | None = None
        self._warned = False
        self._lock = threading.Lock()

    # -- Engine lifecycle ---------------------------------------------------
    def _create_engine(self):
        """Create the real speech engine. Overridden in tests."""
        import pyttsx3

        return pyttsx3.init()

    def _get_engine(self):
        """Return the engine, initialising it once on first use."""
        if self._engine is None and self._init_error is None:
            try:
                self._engine = self._create_engine()
                self._configure(self._engine)
            except Exception as exc:  # noqa: BLE001
                self._init_error = str(exc)
                log.error("TTS engine failed to initialise: %s", exc)
        return self._engine

    def _configure(self, engine) -> None:
        try:
            engine.setProperty("rate", self.rate)
        except Exception:  # noqa: BLE001
            pass
        self.set_voice(self.voice_name)

    def _discard_engine(self) -> None:
        """Drop a broken engine so the next speak re-creates it fresh."""
        try:
            if self._engine is not None:
                self._engine.stop()
        except Exception:  # noqa: BLE001
            pass
        self._engine = None

    @property
    def available(self) -> bool:
        """True if a speech engine could be initialised."""
        return self._get_engine() is not None

    # -- Public controls ----------------------------------------------------
    def list_voices(self) -> list[str]:
        """Names of the voices the system can speak with."""
        engine = self._get_engine()
        if engine is None:
            return []
        try:
            return [v.name for v in engine.getProperty("voices")]
        except Exception:  # noqa: BLE001
            return []

    def set_rate(self, rate: int) -> None:
        """Speech speed in words per minute (clamped to a sane range)."""
        self.rate = max(80, min(400, int(rate)))
        engine = self._get_engine()
        if engine is not None:
            try:
                engine.setProperty("rate", self.rate)
            except Exception:  # noqa: BLE001
                pass

    def set_voice(self, name: str) -> None:
        """Select a voice by its name; no-op if the name is not found."""
        self.voice_name = name
        engine = self._get_engine()
        if engine is None or not name:
            return
        try:
            for voice in engine.getProperty("voices"):
                if voice.name == name:
                    engine.setProperty("voice", voice.id)
                    return
        except Exception:  # noqa: BLE001
            pass

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if not enabled:
            self.stop()

    def stop(self) -> None:
        """Stop any speech currently being spoken."""
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:  # noqa: BLE001
                pass

    # -- Speaking -----------------------------------------------------------
    def speak(self, text: str, emotion: str | None = None) -> bool:
        """Speak `text` (blocking). Returns False if nothing was spoken.

        Safe to call from any thread thanks to the lock. ``emotion`` is an
        optional tone hint (happy/sad/angry) that nudges the speaking rate
        up or down when mood emphasis is enabled (Phase 30).
        """
        if not self.enabled or not (text or "").strip():
            return False

        # A previous runAndWait() can hang after the audio finishes without
        # ever releasing the lock (Phase 22 quirk). Do not wait forever:
        # force-stop the wedged engine so this reply can still be spoken.
        if not self._lock.acquire(timeout=1.0):
            self.stop()
            if not self._lock.acquire(timeout=5.0):
                log.error("TTS engine is stuck; skipping this reply")
                return False
        try:
            engine = self._get_engine()
            if engine is None:
                if not self._warned:
                    log.error("TTS unavailable, continuing text-only: %s", self._init_error)
                    self._warned = True
                return False
            rate = self._mood_rate(emotion)
            try:
                engine.setProperty("rate", rate)
                engine.say(text)
                engine.runAndWait()
                engine.setProperty("rate", self.rate)
                return True
            except Exception as exc:  # noqa: BLE001
                log.error("TTS speak failed: %s", exc)
                # The engine may be unhealthy after an exception (e.g. a
                # wedged runAndWait). Drop it so the next call re-creates
                # a fresh one instead of silently swallowing replies.
                self._discard_engine()
                return False
        finally:
            self._lock.release()

    def _mood_rate(self, emotion: str | None) -> int:
        """A slight rate shift for the detected tone (mood-adapted voice)."""
        if not self.mood_emphasis or not emotion:
            return self.rate
        mood = emotion.lower()
        if mood == "happy":
            return min(400, self.rate + 25)
        if mood in ("sad", "angry"):
            return max(80, self.rate - 25)
        return self.rate


def get_tts_service(cfg=settings) -> TTSService:
    """Create a TTS service from the current configuration."""
    return TTSService(
        enabled=cfg.tts_enabled,
        rate=cfg.tts_speed,
        voice_name=cfg.tts_voice,
        mood_emphasis=bool(getattr(cfg, "tts_mood_emphasis", True)),
    )
