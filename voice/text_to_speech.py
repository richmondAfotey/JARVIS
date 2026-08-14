"""
Text-to-speech service.

Turns JARVIS replies into spoken words.

Two backends are supported (selected with ``settings.tts_engine``):

    * ``"system"`` (default) - the offline Windows voices (SAPI5, via the
      ``pyttsx3`` library). No internet and no API key required.
    * ``"edge"`` - natural neural voices streamed from Microsoft Edge's
      online TTS (the ``edge-tts`` library). Needing internet, so if it is
      not installed / unreachable the service logs the reason and returns
      False - the app then simply continues in text-only mode.

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

import asyncio
import os
import tempfile
import threading
import time
from pathlib import Path

from config import settings
from utils.logger import get_logger

log = get_logger(__name__)

#: Well-known natural voices for the edge-tts backend (Phase 36). Pass the
#: chosen name via TTS_VOICE / TTS_EDGE_VOICE or pick one in Settings.
EDGE_VOICES = [
    "en-US-EmmaNeural",
    "en-US-GuyNeural",
    "en-US-JennyNeural",
    "en-US-MichelleNeural",
    "en-GB-SoniaNeural",
    "en-GB-RyanNeural",
    "en-AU-NatashaNeural",
    "en-CA-ClaraNeural",
    "en-IN-NeerjaNeural",
]


class TTSService:
    def __init__(
        self,
        enabled: bool = True,
        rate: int = 180,
        voice_name: str = "",
        mood_emphasis: bool = True,
        engine: str = "system",
        edge_voice: str = "",
    ):
        self.enabled = enabled
        self.rate = rate
        self.voice_name = voice_name
        # Phase 30: when True, spoken replies are slowed slightly for
        # "sad" tone hints and sped up for a cheerful "happy" hint, so the
        # voice matches the mood JARVIS detected in the user's speech.
        self.mood_emphasis = mood_emphasis
        # Phase 36: "system" (offline SAPI5) or "edge" (natural neural).
        self.engine = engine
        self.edge_voice = edge_voice
        self._engine = None
        self._init_error: str | None = None
        self._warned = False
        self._lock = threading.Lock()
        # Set when stop() is called so a long edge-tts playback is cut short.
        self._edge_stop = threading.Event()

    # -- Engine lifecycle ---------------------------------------------------
    def _create_engine(self):
        """Create the real (system) speech engine. Overridden in tests."""
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
        """True if the configured backend could produce speech."""
        if self.engine == "edge":
            try:
                import edge_tts  # noqa: PLC0415, F401

                return True
            except Exception:  # noqa: BLE001
                return False
        return self._get_engine() is not None

    # -- Public controls ----------------------------------------------------
    def list_voices(self) -> list[str]:
        """Names of the voices the system can speak with."""
        if self.engine == "edge":
            return list(EDGE_VOICES)
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
        if self.engine == "edge":
            return
        engine = self._get_engine()
        if engine is not None:
            try:
                engine.setProperty("rate", self.rate)
            except Exception:  # noqa: BLE001
                pass

    def set_voice(self, name: str) -> None:
        """Select a voice by its name; no-op if the name is not found."""
        self.voice_name = name
        if self.engine == "edge":
            return
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
        self._edge_stop.set()
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            import sounddevice as sd  # noqa: PLC0415

            sd.stop()
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

        if self.engine == "edge":
            with self._lock:
                return self._speak_edge(text, emotion)

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

    # -- Edge (natural neural) backend --------------------------------------
    def _speak_edge(self, text: str, emotion: str | None) -> bool:
        """Synthesize with edge-tts and play it, honouring stop().

        Everything is imported lazily: if edge-tts (or the audio stack) is
        missing the method logs why and returns False, so the app carries on
        in text-only mode just like the system backend does when unavailable.
        """
        try:
            import edge_tts  # noqa: PLC0415
            import sounddevice as sd  # noqa: PLC0415
            import soundfile as sf  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            if not self._warned:
                log.error(
                    "edge-tts backend unavailable, continuing text-only: %s", exc
                )
                self._warned = True
            return False

        voice = self.voice_name or self.edge_voice or EDGE_VOICES[0]
        rate = self._edge_rate(emotion)
        tmp = Path(
            tempfile.gettempdir(),
            f"jarvis_edge_{os.getpid()}_{time.time_ns()}.mp3",
        )
        self._edge_stop.clear()
        try:
            async def _synth() -> None:
                communicate = edge_tts.Communicate(text, voice, rate=rate)
                await communicate.save(str(tmp))

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(_synth())
            finally:
                loop.close()

            if self._edge_stop.is_set():
                return False
            data, sample_rate = sf.read(str(tmp))
            self._play_edge(data, sample_rate, sd)
            return True
        except Exception as exc:  # noqa: BLE001 - synthesis must never crash
            log.error("edge-tts speak failed: %s", exc)
            return False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    def _play_edge(self, data, sample_rate, sd) -> None:
        """Stream decoded audio to the sound card in small blocks.

        Listening between blocks lets stop() interrupt a long reply quickly
        instead of playing it all the way through.
        """
        import numpy as np  # noqa: PLC0415

        mono = data if data.ndim == 1 else np.mean(data, axis=1)
        block = int(sample_rate * 0.1)
        with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32") as out:
            for i in range(0, len(mono), block):
                if self._edge_stop.is_set():
                    break
                out.write(np.asarray(mono[i : i + block], dtype="float32"))
        sd.stop()

    def _edge_rate(self, emotion: str | None) -> str:
        """A slight rate shift for the detected tone (mood-adapted voice).

        edge-tts takes a prosody percentage (e.g. ``"+10%"``) rather than a
        words-per-minute figure, so mood hints become small percentage nudges.
        """
        if not self.mood_emphasis or not emotion:
            return "+0%"
        mood = emotion.lower()
        if mood == "happy":
            return "+8%"
        if mood in ("sad", "angry"):
            return "-8%"
        return "+0%"

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
        engine=cfg.tts_engine,
        edge_voice=getattr(cfg, "tts_edge_voice", "") or "",
    )
