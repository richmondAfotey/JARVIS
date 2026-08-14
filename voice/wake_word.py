"""
Wake-word listener - "Hey JARVIS" activation.

How it works (realistic, resource-friendly design):

1. A background thread continuously reads small microphone blocks and
   performs *voice-activity detection* (VAD) using signal energy - this
   step is fully local and offline.
2. Only when speech is actually heard does it record a short utterance
   (a few seconds) and transcribe it with the configured speech
   recognizer (Google by default, so wake-word detection needs internet
   when a phrase is spoken).
3. If the transcription contains the wake phrase (or the assistant
   name), the `on_wake` callback fires.

This means the network/API is only used when someone is talking near the
microphone, not constantly.

IMPORTANT safety design:
    * The listener is OFF by default. Enabling it is an explicit,
      visible user action (a button that lights up / a setting).
    * The app shows a visible indicator while it is running.
    * The listener can be paused (e.g. while JARVIS is speaking) to
      avoid the assistant waking itself up through the speakers.
"""

from __future__ import annotations

import threading
import time

from utils.helpers import normalize_text
from utils.logger import get_logger

from voice.speech_to_text import (
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    STTError,
    _frames_to_pcm16,
    _has_sounddevice,
)

log = get_logger(__name__)

# Lazy-loaded on the background thread (Phase 20: keep module import cheap).
np = None
sd = None
AudioData = None


def _init_libs() -> None:
    """Import numpy/sounddevice/AudioData on the first wake-loop iteration."""
    global np, sd, AudioData
    if np is None:
        import numpy  # noqa: PLC0415
        np = numpy
        import sounddevice as _sd  # noqa: PLC0415
        sd = _sd
        from speech_recognition import AudioData as _ad  # noqa: PLC0415
        AudioData = _ad


class WakeWordListener:
    def __init__(
        self,
        wake_phrase: str,
        stt,
        on_wake,
        assistant_name: str = "JARVIS",
        sample_rate: int = SAMPLE_RATE,
        vad_threshold: float = 0.015,
        max_utterance: float = 3.0,
        silence_after: float = 0.8,
        cooldown: float = 3.0,
        poll_seconds: float = 0.25,
    ):
        self.wake_phrase = normalize_text(wake_phrase)
        self.stt = stt
        self.on_wake = on_wake
        self.trigger_words = {normalize_text(assistant_name)}
        self.sample_rate = sample_rate
        self.vad_threshold = vad_threshold
        self.max_utterance = max_utterance
        self.silence_after = silence_after
        self.cooldown = cooldown
        self.poll_seconds = poll_seconds

        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._paused.set()  # starts paused; start() resumes it
        self._thread: threading.Thread | None = None
        self._cooldown_until = 0.0

    # -- Lifecycle ----------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._paused.set()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="wake-word")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._paused.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def pause(self) -> None:
        """Temporarily ignore the microphone (e.g. while speaking)."""
        self._paused.clear()

    def resume(self) -> None:
        """Start paying attention again."""
        self._paused.set()
        self._reset_state()

    def _reset_state(self) -> None:
        self._speech_frames: list[bytes] = []
        self._heard_speech = False
        self._silence_since: float | None = None
        self._utterance_start: float | None = None

    # -- Background loop -----------------------------------------------------
    def _audio_blocks(self):
        """Yield microphone blocks as float32 arrays.

        Overridden in tests to supply synthetic audio.
        """
        if not _has_sounddevice():
            raise RuntimeError("sounddevice not available")
        _init_libs()
        blocksize = int(self.sample_rate * self.poll_seconds)
        while not self._stop_event.is_set():
            # While paused, do not hold the microphone open: the assistant
            # may be recording from it, and a second open input stream can
            # come back silent on Windows. Reopen the stream on resume.
            self._paused.wait()
            try:
                with sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=blocksize,
                ) as stream:
                    while not self._stop_event.is_set():
                        if not self._paused.is_set():
                            break  # paused mid-block: close and wait
                        yield stream.read(blocksize)[0]
            except Exception as exc:  # noqa: BLE001
                if not self._stop_event.is_set() and self._paused.is_set():
                    log.error("Wake word microphone error: %s", exc)
                    time.sleep(1.0)

    def _loop(self) -> None:
        try:
            for block in self._audio_blocks():
                if self._stop_event.is_set():
                    break
                self._feed(block)
        except Exception as exc:  # noqa: BLE001
            log.error("Wake word listener stopped unexpectedly: %s", exc)

    # -- VAD + matching ------------------------------------------------------
    def _feed(self, block: np.ndarray) -> None:
        if not self._paused.is_set():
            # Paused - drop audio and forget any partial speech.
            self._reset_state()
            return

        if not hasattr(self, "_heard_speech"):
            self._reset_state()

        if np is None:
            _init_libs()
        rms = float(np.sqrt(np.mean(np.square(block)))) if block.size else 0.0

        if rms > self.vad_threshold:
            # Speech energy: start (or continue) an utterance.
            if not self._heard_speech:
                self._heard_speech = True
                self._utterance_start = time.time()
            self._silence_since = None
            self._speech_frames.append(_frames_to_pcm16(block))
            if time.time() - self._utterance_start >= self.max_utterance:
                self._handle_utterance()
            return

        # Quiet block.
        if not self._heard_speech:
            return  # no speech yet - keep waiting

        if self._silence_since is None:
            self._silence_since = time.time()  # first silence after speech
        if time.time() - self._silence_since >= self.silence_after:
            self._handle_utterance()

    def _handle_utterance(self) -> None:
        frames = b"".join(getattr(self, "_speech_frames", []) or [])
        self._reset_state()
        if not frames:
            return
        if time.time() < self._cooldown_until:
            return  # recently woke up - ignore

        if AudioData is None:
            _init_libs()
        audio = AudioData(frames, self.sample_rate, SAMPLE_WIDTH)
        try:
            text = self.stt.recognize(audio)
        except STTError:
            return  # could not transcribe - not a wake event
        except Exception as exc:  # noqa: BLE001
            log.debug("Wake recognition failed: %s", exc)
            return

        if self._matches(text):
            self._cooldown_until = time.time() + self.cooldown
            log.info("Wake word detected: %r", text)
            try:
                self.on_wake()
            except Exception as exc:  # noqa: BLE001
                log.error("on_wake callback failed: %s", exc)

    def _matches(self, text: str) -> bool:
        """True if the transcription contains the wake phrase or the name."""
        norm = normalize_text(text)
        if not norm:
            return False
        if self.wake_phrase and self.wake_phrase in norm:
            return True
        words = set(norm.split())
        return bool(words & self.trigger_words)
