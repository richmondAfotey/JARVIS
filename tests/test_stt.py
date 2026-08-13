"""Tests for the speech-to-text service (uses fakes - no microphone)."""

import pytest

import speech_recognition as sr
from speech_recognition import AudioData

from voice.speech_to_text import (
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    SpeechToText,
    STTError,
    _frames_to_pcm16,
)
import numpy as np


# -- helpers ----------------------------------------------------------------

def make_fake_audio(seconds: float = 1.0) -> AudioData:
    """Silent 16-bit PCM audio (all zeros)."""
    data = b"\x00\x00" * int(SAMPLE_RATE * seconds)
    return AudioData(data, SAMPLE_RATE, SAMPLE_WIDTH)


class FakeRecognizer:
    """Stand-in for speech_recognition.Recognizer."""

    def __init__(self, result="", error=None):
        self.result = result
        self.error = error
        self.called_with = None

    def recognize_google(self, audio, **kwargs):
        self.called_with = audio
        if self.error:
            raise self.error
        return self.result


# -- pcm conversion ----------------------------------------------------------

def test_frames_to_pcm16_shape():
    data = np.zeros((1600, 1), dtype=np.float32)
    raw = _frames_to_pcm16(data)
    assert len(raw) == 1600 * 2  # 16-bit = 2 bytes per sample


def test_frames_to_pcm16_clips():
    data = np.array([[2.0], [-2.0], [0.5]], dtype=np.float32)
    raw = _frames_to_pcm16(data)
    samples = np.frombuffer(raw, dtype=np.int16)
    assert samples[0] == 32767  # clipped to max
    assert samples[1] == -32767  # clipped to min
    assert samples[2] > 15000  # 0.5 * 32767


# -- availability ------------------------------------------------------------

def test_mic_available_false_when_library_missing(monkeypatch):
    stt = SpeechToText()
    monkeypatch.setattr("voice.speech_to_text._HAS_SOUNDDEVICE", False)
    assert stt.mic_available() is False


# -- recognize --------------------------------------------------------------

def test_recognize_returns_text(monkeypatch):
    stt = SpeechToText()
    fake = FakeRecognizer(result="open the weather app")
    monkeypatch.setattr(stt, "_get_recognizer", lambda: fake)

    audio = make_fake_audio()
    assert stt.recognize(audio) == "open the weather app"
    assert fake.called_with is audio


def test_recognize_none_audio_raises(monkeypatch):
    stt = SpeechToText()
    monkeypatch.setattr(stt, "_get_recognizer", FakeRecognizer())
    with pytest.raises(STTError):
        stt.recognize(None)


def test_recognize_unknown_value(monkeypatch):
    stt = SpeechToText()
    fake = FakeRecognizer(error=sr.UnknownValueError())
    monkeypatch.setattr(stt, "_get_recognizer", lambda: fake)
    with pytest.raises(STTError, match="could not understand"):
        stt.recognize(make_fake_audio())


def test_recognize_request_error(monkeypatch):
    stt = SpeechToText()
    fake = FakeRecognizer(error=sr.RequestError("no internet"))
    monkeypatch.setattr(stt, "_get_recognizer", lambda: fake)
    with pytest.raises(STTError, match="offline"):
        stt.recognize(make_fake_audio())


def test_recognize_unknown_provider():
    stt = SpeechToText(provider="not-a-provider")
    with pytest.raises(STTError, match="Unknown speech provider"):
        stt.recognize(make_fake_audio())


def test_recognize_google_passes_language(monkeypatch):
    stt = SpeechToText(provider="google", language="fr-FR")
    calls = {}

    class FakeRecognizer:
        def recognize_google(self, audio, language=""):
            calls["language"] = language
            return "bonjour"

    monkeypatch.setattr(stt, "_get_recognizer", lambda: FakeRecognizer())
    assert stt.recognize(make_fake_audio()) == "bonjour"
    assert calls["language"] == "fr-FR"


def test_recognize_google_default_language(monkeypatch):
    stt = SpeechToText(provider="google")
    kwargs = {}

    class FakeRecognizer:
        def recognize_google(self, audio, **kw):
            kwargs.update(kw)
            return "hi"

    monkeypatch.setattr(stt, "_get_recognizer", lambda: FakeRecognizer())
    assert stt.recognize(make_fake_audio()) == "hi"
    assert "language" not in kwargs


# -- listen flow ------------------------------------------------------------

def test_listen_raises_when_no_speech(monkeypatch):
    stt = SpeechToText()
    monkeypatch.setattr(stt, "record", lambda timeout=None: None)
    with pytest.raises(STTError, match="No speech"):
        stt.listen()


def test_listen_full_flow(monkeypatch):
    stt = SpeechToText()
    audio = make_fake_audio()
    monkeypatch.setattr(stt, "record", lambda timeout=None: audio)
    fake = FakeRecognizer(result="hello")
    monkeypatch.setattr(stt, "_get_recognizer", lambda: fake)
    assert stt.listen() == "hello"
