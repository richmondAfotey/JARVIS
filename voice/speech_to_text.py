"""
Speech recognition service.

Turns microphone audio into text using the `SpeechRecognition` library.
The default recognizer (`recognize_google`) is free and needs internet.
If there is no microphone or no internet, the service reports a clear,
friendly error instead of crashing - the app continues in text-only mode.

Mic capture uses `sounddevice` (PortAudio) because `pyaudio` does not yet
ship prebuilt wheels for Python 3.14.

The recognizer and the capture loop are separated so tests can replace
them with fakes (no microphone needed on the test machine).
"""

from __future__ import annotations

import threading
import time

from utils.logger import get_logger

from voice.emotion import EmotionDetector

log = get_logger(__name__)

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # 16-bit PCM bytes per sample

# Optional third-party libraries, loaded lazily on first use (Phase 20:
# importing this module must stay cheap so the app starts fast).
np = None
sd = None
sr = None
AudioData = None
_HAS_SOUNDDEVICE: bool | None = None
_HAS_SPEECHRECOGNITION: bool | None = None
_libs_ready = False


def _init_libs() -> None:
    """Import numpy/sounddevice/speech_recognition on first use."""
    global np, sd, sr, AudioData, _HAS_SOUNDDEVICE, _HAS_SPEECHRECOGNITION, _libs_ready
    if _libs_ready:
        return
    import numpy  # noqa: PLC0415
    np = numpy

    try:
        import sounddevice as _sd  # noqa: PLC0415
        sd = _sd
        _HAS_SOUNDDEVICE = True
    except Exception:  # noqa: BLE001
        _HAS_SOUNDDEVICE = False

    try:
        import speech_recognition as _sr  # noqa: PLC0415
        from speech_recognition import AudioData as _ad  # noqa: PLC0415
        sr = _sr
        AudioData = _ad
        _HAS_SPEECHRECOGNITION = True
    except Exception:  # noqa: BLE001
        _HAS_SPEECHRECOGNITION = False

    _libs_ready = True


class STTError(RuntimeError):
    """Raised when speech recognition cannot produce text."""


def _has_sounddevice() -> bool:
    if _HAS_SOUNDDEVICE is None:
        _init_libs()
    return bool(_HAS_SOUNDDEVICE)


def _has_speechrecognition() -> bool:
    if _HAS_SPEECHRECOGNITION is None:
        _init_libs()
    return bool(_HAS_SPEECHRECOGNITION)


def _frames_to_pcm16(data) -> bytes:
    """Convert a float32 sample block into 16-bit PCM bytes."""
    if np is None:
        _init_libs()
    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
    return pcm.tobytes()


class SpeechToText:
    def __init__(
        self,
        provider: str = "google",
        sample_rate: int = SAMPLE_RATE,
        silence_threshold: float = 0.008,
        silence_after: float = 0.9,
        max_timeout: float = 8.0,
        language: str = "",
    ):
        self.provider = provider
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold
        self.silence_after = silence_after
        self.max_timeout = max_timeout
        self.language = language or ""
        self._lock = threading.Lock()
        self._recognizer = None  # lazy: sr.Recognizer()
        self._listening = False

    # -- Availability -------------------------------------------------------
    @property
    def libraries_available(self) -> bool:
        return _has_sounddevice() and _has_speechrecognition()

    def mic_available(self) -> bool:
        """True if a default input (microphone) device exists."""
        if not _has_sounddevice():
            return False
        try:
            device = sd.query_devices(kind="input")
            return device is not None and device["max_input_channels"] > 0
        except Exception:  # noqa: BLE001
            return False

    # -- Recording ----------------------------------------------------------
    def record(self, timeout: float | None = None) -> AudioData | None:
        """Record one phrase of speech from the microphone.

        Returns an `AudioData` object, or None if no speech was heard
        within `timeout` seconds.
        """
        timeout = timeout or self.max_timeout
        if not _has_sounddevice():
            raise STTError("Microphone capture is not available on this system.")

        chunk_seconds = 0.25
        blocksize = int(self.sample_rate * chunk_seconds)
        frames: list[bytes] = []
        silence_blocks = 0
        heard_speech = False
        start = time.time()

        # Adaptive noise gate instead of a fixed threshold. A fixed threshold
        # was brittle: a quiet microphone (or speech spoken far from it) never
        # crossed it, so record() returned None and the UI said "No speech
        # detected" while the user was clearly talking. We track a rolling
        # noise floor from the quiet blocks and gate on
        # max(silence_threshold, floor * 2): quiet rooms fall back to the
        # threshold, noisy rooms raise the gate so room tone isn't heard as
        # speech. Two consecutive above-gate blocks are required before the
        # recording starts, so a single loud blip doesn't fake speech.
        abs_floor = self.silence_threshold
        noise_floor = 0.0
        candidate: list[bytes] = []
        peak_rms = 0.0

        with sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            while time.time() - start < timeout:
                data, _overflowed = stream.read(blocksize)
                rms = float(np.sqrt(np.mean(np.square(data)))) if data.size else 0.0
                peak_rms = max(peak_rms, rms)

                gate = max(abs_floor, noise_floor * 2.0)
                if rms > gate:
                    candidate.append(_frames_to_pcm16(data))
                    if len(candidate) >= 2:
                        frames.extend(candidate)
                        candidate = []
                        heard_speech = True
                        silence_blocks = 0
                elif heard_speech:
                    silence_blocks += 1
                    if silence_blocks * chunk_seconds >= self.silence_after:
                        break
                else:
                    # No speech yet: keep learning the room tone so a loud
                    # room raises the gate instead of faking speech.
                    candidate.clear()
                    noise_floor = noise_floor * 0.8 + rms * 0.2

        if not heard_speech or not frames:
            self._last_no_speech_note = self._no_speech_note(peak_rms)
            return None
        self._last_no_speech_note = None
        return AudioData(b"".join(frames), self.sample_rate, SAMPLE_WIDTH)

    def _no_speech_note(self, peak_rms: float) -> str | None:
        """A friendlier explanation for record() returning None."""
        if peak_rms > self.silence_threshold * 2:
            return (
                "I heard sound but couldn't make out clear speech. "
                "Please speak more clearly or move closer to the microphone."
            )
        return None

    # -- Recognition --------------------------------------------------------
    def _get_recognizer(self):
        if self._recognizer is None:
            if not _has_speechrecognition():
                raise STTError(
                    "The 'SpeechRecognition' library is not installed. "
                    "Run: pip install SpeechRecognition"
                )
            self._recognizer = sr.Recognizer()
        return self._recognizer

    def recognize(self, audio: AudioData) -> str:
        """Convert recorded audio into text (requires internet for google)."""
        if audio is None:
            raise STTError("No speech detected.")
        recognizer = self._get_recognizer()
        try:
            if self.provider == "google":
                if self.language:
                    return recognizer.recognize_google(audio, language=self.language)
                return recognizer.recognize_google(audio)
            if self.provider in ("whisper", "openai"):
                # Local, offline transcription via openai-whisper (Phase 30).
                # `recognize_whisper(audio, model=...)` downloads the model on
                # first use, then works fully offline.
                try:
                    import speech_recognition as _sr  # type: ignore  # noqa: PLC0415
                    return recognizer.recognize_whisper(
                        audio,
                        model=_sr.whisper_default_model(),
                        language=self.language or None,
                    )
                except (AttributeError, TypeError):
                    # Older SpeechRecognition builds: no model default helper.
                    return recognizer.recognize_whisper(
                        audio, language=self.language or None
                    )
            # Future providers can be added here (whisper, openai, ...).
            raise STTError(f"Unknown speech provider: {self.provider}")
        except STTError:
            raise
        except sr.UnknownValueError:
            raise STTError("I could not understand what was said. Please try again.") from None
        except sr.RequestError as exc:
            log.error("Speech recognition request failed: %s", exc)
            raise STTError(
                "Speech recognition is offline. Check your internet connection, "
                "then try again."
            ) from exc

    # -- Full flow ----------------------------------------------------------
    def listen(self, timeout: float | None = None) -> str:
        """Record and transcribe one utterance. Raises STTError on failure."""
        with self._lock:
            self._listening = True
            try:
                audio = self.record(timeout)
                if audio is None:
                    note = getattr(self, "_last_no_speech_note", None) or (
                        "No speech detected."
                    )
                    raise STTError(note)
                return self.recognize(audio)
            finally:
                self._listening = False

    def listen_with_emotion(self, timeout: float | None = None):
        """Record one utterance: return ``(text, emotion_result)``.

        ``text`` is the transcription (same as :meth:`listen`); the mood is
        estimated from the *tone of the recorded audio* by the voice-tone
        detector (happy / sad / angry / neutral). ``emotion_result`` is
        None when nothing was heard. Raises STTError on recognition failure.
        """
        with self._lock:
            self._listening = True
            try:
                audio = self.record(timeout)
                if audio is None:
                    note = getattr(self, "_last_no_speech_note", None) or (
                        "No speech detected."
                    )
                    raise STTError(note)
                emotion = self._detect_emotion(audio)
                return self.recognize(audio), emotion
            finally:
                self._listening = False

    def _detect_emotion(self, audio: AudioData | None):
        """Run tone-of-voice detection on recorded audio (may be None)."""
        if audio is None:
            return None
        try:
            detector = EmotionDetector(sample_rate=self.sample_rate)
            return detector.detect_from_audiodata(audio)
        except Exception as exc:  # noqa: BLE001 - tone hints must never break speech
            log.debug("Emotion detection skipped: %s", exc)
            return None
