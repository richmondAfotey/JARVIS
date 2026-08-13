"""Tests for tone-of-voice emotion detection (Phase 29).

Uses deterministic synthetic tones (no microphone needed): simple sine
waves shaped with modulation, harmonics and noise to mimic the acoustics
of happy / sad / angry / neutral speech.
"""

import pytest

import numpy as np
from speech_recognition import AudioData

from ai.brain import Brain
from ai.providers.local_echo import LocalEchoProvider
from voice.emotion import EmotionDetector, EmotionResult
from voice.speech_to_text import SAMPLE_RATE, SAMPLE_WIDTH, SpeechToText

SR = SAMPLE_RATE


# -- synthetic speech helpers -----------------------------------------------

def make_tone(
    f0: float,
    seconds: float = 2.0,
    amp: float = 0.5,
    am_hz: float = 0.0,
    depth: float = 0.0,
    noise: float = 0.0,
    harmonics: tuple = (),
    seed: int = 0,
) -> np.ndarray:
    """Return int16 PCM of a shaped tone, emulating a speaking style."""
    t = np.arange(int(SR * seconds)) / SR
    x = amp * np.sin(2 * np.pi * f0 * t)
    for order, weight in harmonics:
        x += amp * weight * np.sin(2 * np.pi * f0 * order * t)
    if am_hz:
        env = 1 - depth * 0.5 + depth * 0.5 * np.sin(2 * np.pi * am_hz * t)
        x *= env
    if noise:
        x += noise * np.random.RandomState(seed).randn(len(t))
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def happy_tone() -> np.ndarray:
    # Bright, high-pitched, lively.
    return make_tone(
        280, amp=0.5, am_hz=6.0, depth=0.6,
        harmonics=[(2, 0.4), (3, 0.25), (4, 0.15), (5, 0.1)],
    )


def sad_tone() -> np.ndarray:
    # Quiet, low-pitched, flat.
    return make_tone(110, amp=0.12)


def angry_tone() -> np.ndarray:
    # Loud, harsh, low-mid pitch.
    return make_tone(
        140, amp=0.8, am_hz=7.0, depth=0.5, noise=0.3,
        harmonics=[(2, 0.5), (3, 0.3)],
    )


def neutral_tone() -> np.ndarray:
    # Mid pitch, quiet, flat.
    return make_tone(180, amp=0.3)


# -- detector behaviour -----------------------------------------------------

def test_detects_happy():
    result = EmotionDetector().detect_from_pcm(happy_tone(), SR)
    assert result.emotion == "happy"
    assert 0.0 <= result.confidence <= 1.0


def test_detects_sad():
    result = EmotionDetector().detect_from_pcm(sad_tone(), SR)
    assert result.emotion == "sad"


def test_detects_angry():
    result = EmotionDetector().detect_from_pcm(angry_tone(), SR)
    assert result.emotion == "angry"


def test_calm_mid_pitch_stays_neutral():
    result = EmotionDetector().detect_from_pcm(neutral_tone(), SR)
    assert result.emotion == "neutral"


def test_silence_is_neutral():
    result = EmotionDetector().detect_from_pcm(np.zeros(SR, dtype=np.int16), SR)
    assert result.emotion == "neutral"


def test_short_audio_is_neutral():
    result = EmotionDetector().detect_from_pcm(np.zeros(100, dtype=np.int16), SR)
    assert result.emotion == "neutral"


def test_accepts_float_array():
    det = EmotionDetector()
    happy = happy_tone()
    pcm = det.detect_from_pcm(happy, SR)
    floats = happy.astype(np.float32) / 32768.0
    assert det.detect_from_pcm(floats, SR).emotion == pcm.emotion


def test_valence_axis_reflects_mood():
    det = EmotionDetector()
    assert det.detect_from_pcm(happy_tone(), SR).valence > 0
    assert det.detect_from_pcm(sad_tone(), SR).valence < 0
    assert det.detect_from_pcm(angry_tone(), SR).valence < 0
    assert det.detect_from_pcm(neutral_tone(), SR).valence == 0.0


def test_detect_from_audiodata():
    audio = AudioData(happy_tone().tobytes(), SR, SAMPLE_WIDTH)
    result = EmotionDetector().detect_from_audiodata(audio)
    assert result is not None
    assert result.emotion == "happy"


def test_detect_from_audiodata_none_is_none():
    assert EmotionDetector().detect_from_audiodata(None) is None


# -- STT integration --------------------------------------------------------

class FakeRecognizer:
    def __init__(self, result: str, error=None):
        self.result = result
        self.error = error

    def recognize_google(self, audio, **kwargs):
        if self.error:
            raise self.error
        return self.result


def test_listen_with_emotion_returns_text_and_tone(monkeypatch):
    stt = SpeechToText()
    audio = AudioData(sad_tone().tobytes(), SR, SAMPLE_WIDTH)
    monkeypatch.setattr(stt, "record", lambda timeout=None: audio)
    monkeypatch.setattr(stt, "_get_recognizer", lambda: FakeRecognizer("im tired"))
    text, emotion = stt.listen_with_emotion()
    assert text == "im tired"
    assert emotion is not None
    assert emotion.emotion == "sad"


def test_listen_with_emotion_no_speech_raises(monkeypatch):
    stt = SpeechToText()
    monkeypatch.setattr(stt, "record", lambda timeout=None: None)
    with pytest.raises(Exception):
        text, _ = stt.listen_with_emotion()
        assert text is None


def test_listen_with_emotion_failed_recognition(monkeypatch):
    import speech_recognition as sr

    stt = SpeechToText()
    audio = AudioData(neutral_tone().tobytes(), SR, SAMPLE_WIDTH)
    monkeypatch.setattr(stt, "record", lambda timeout=None: audio)
    monkeypatch.setattr(
        stt, "_get_recognizer", lambda: FakeRecognizer("", error=sr.UnknownValueError())
    )
    with pytest.raises(Exception):
        stt.listen_with_emotion()


# -- Brain integration ------------------------------------------------------

class _PersistRecorder:
    """Stand-in database that records what Brain would persist."""

    def __init__(self):
        self.saved: list[tuple[str, str]] = []

    def save_message(self, role, content):
        self.saved.append((role, content))

    def list_memories(self, **kwargs):
        return []


def test_brain_respond_accepts_emotion():
    brain = Brain(provider=LocalEchoProvider())
    reply = brain.respond("hello", emotion="sad")
    assert reply
    # The transcription is preserved at the start of the model-facing text.
    last_user = next(
        m["content"] for m in reversed(brain.conversation.messages)
        if m["role"] == "user"
    )
    assert last_user.startswith("hello")


def test_brain_tone_hint_included_for_model_but_not_persisted():
    db = _PersistRecorder()
    brain = Brain(provider=LocalEchoProvider(), database=db)
    brain.respond("i don't feel well", emotion="sad")
    # The AI sees the hint (so it can match the mood)...
    assert any("voice-tone hint" in m.get("content", "") for m in brain.conversation.messages)
    # ...but only the clean transcription is written to storage.
    persisted_user = [c for r, c in db.saved if r == "user"]
    assert persisted_user == ["i don't feel well"]
    assert all("voice-tone hint" not in c for c in persisted_user)


def test_brain_neutral_or_missing_emotion_adds_no_hint():
    brain = Brain(provider=LocalEchoProvider())
    brain.respond("hello", emotion=None)
    brain.respond("hi there", emotion="neutral")
    assert all("voice-tone hint" not in m.get("content", "") for m in brain.conversation.messages)