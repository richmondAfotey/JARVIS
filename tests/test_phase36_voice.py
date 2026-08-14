"""Tests for Phase 36: natural edge-tts voice + continuous conversation.

The edge backend is exercised with fake edge_tts / soundfile / sounddevice
modules so no internet, Microsoft service, or audio hardware is needed.
"""

import sys
import types
from pathlib import Path

import numpy as np
import pytest

from voice.text_to_speech import EDGE_VOICES, TTSService, get_tts_service


class FakeEdgeTTS:
    class Communicate:
        calls = []

        def __init__(self, text, voice, rate):
            self.text = text
            self.voice = voice
            self.rate = rate

        async def save(self, path):
            FakeEdgeTTS.Communicate.calls.append(
                {"text": self.text, "voice": self.voice, "rate": self.rate}
            )
            Path(path).write_bytes(b"fake-mp3")

        @staticmethod
        def _clear():
            FakeEdgeTTS.Communicate.calls = []


class FakeStream:
    def __enter__(self):
        self.written = []
        return self

    def __exit__(self, *exc):
        return False

    def write(self, block):
        self.written.append(block)


class FakeSoundDevice:
    stream = None
    stopped = 0

    @classmethod
    def OutputStream(cls, *args, **kwargs):
        cls.stream = FakeStream()
        return cls.stream

    @classmethod
    def stop(cls):
        cls.stopped += 1


class FakeSoundFile:
    @staticmethod
    def read(path):
        return np.full(500, 0.1, dtype=np.float64), 22050


def install_fake_volume(monkeypatch, edge=True, sndfile=True, snddevice=True):
    """Swap in fake modules for the edge backend (all on by default)."""
    if edge:
        monkeypatch.setitem(sys.modules, "edge_tts", FakeEdgeTTS)
    if sndfile:
        monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFile)
    if snddevice:
        monkeypatch.setitem(sys.modules, "sounddevice", FakeSoundDevice)
    FakeEdgeTTS.Communicate._clear()
    FakeSoundDevice.stream = None
    FakeSoundDevice.stopped = 0


@pytest.fixture
def edge_service():
    service = TTSService(enabled=True, engine="edge", voice_name="en-US-EmmaNeural")
    return service


def test_edge_speak_synthesizes_and_plays(monkeypatch, edge_service):
    install_fake_volume(monkeypatch)
    assert edge_service.speak("Hello there") is True
    saved = FakeEdgeTTS.Communicate.calls
    assert len(saved) == 1
    assert saved[0]["text"] == "Hello there"
    assert saved[0]["voice"] == "en-US-EmmaNeural"
    assert saved[0]["rate"] == "+0%"
    assert FakeSoundDevice.stream is not None
    assert FakeSoundDevice.stream.written


def test_edge_speak_happy_mood_speeds_up(monkeypatch, edge_service):
    install_fake_volume(monkeypatch)
    edge_service.speak("Yay", emotion="happy")
    assert FakeEdgeTTS.Communicate.calls[-1]["rate"] == "+8%"


def test_edge_speak_sad_mood_slows_down(monkeypatch, edge_service):
    install_fake_volume(monkeypatch)
    edge_service.speak("Oh no", emotion="sad")
    assert FakeEdgeTTS.Communicate.calls[-1]["rate"] == "-8%"


def test_edge_speak_mood_ignored_when_disabled(monkeypatch, edge_service):
    install_fake_volume(monkeypatch)
    edge_service.mood_emphasis = False
    edge_service.speak("Flat tone", emotion="happy")
    assert FakeEdgeTTS.Communicate.calls[-1]["rate"] == "+0%"


def test_edge_speak_uses_edge_voice_when_no_named_voice(monkeypatch):
    install_fake_volume(monkeypatch)
    service = TTSService(enabled=True, engine="edge", edge_voice="en-GB-SoniaNeural")
    service.speak("Hello")
    assert FakeEdgeTTS.Communicate.calls[-1]["voice"] == "en-GB-SoniaNeural"


def test_edge_speak_falls_back_silently_when_unavailable(monkeypatch, edge_service):
    import builtins

    real_import = builtins.__import__

    def blocker(name, *args, **kwargs):
        if name.startswith("edge_tts"):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocker)
    assert edge_service.speak("Hello") is False
    assert edge_service.available is False


def test_edge_stop_does_not_crash(monkeypatch, edge_service):
    install_fake_volume(monkeypatch)
    edge_service.stop()
    assert edge_service._edge_stop.is_set()
    assert FakeSoundDevice.stopped >= 1


def test_edge_list_voices_is_curated():
    service = TTSService(engine="edge")
    assert service.list_voices() == EDGE_VOICES
    assert "en-US-EmmaNeural" in EDGE_VOICES
    assert "en-GB-SoniaNeural" in EDGE_VOICES


def test_get_tts_service_passes_engine_config():
    cfg = types.SimpleNamespace(
        tts_enabled=True,
        tts_speed=200,
        tts_voice="",
        tts_mood_emphasis=True,
        tts_engine="edge",
        tts_edge_voice="en-US-GuyNeural",
    )
    service = get_tts_service(cfg)
    assert service.engine == "edge"
    assert service.edge_voice == "en-US-GuyNeural"
    assert service.rate == 200


def test_default_backend_still_system():
    service = TTSService(enabled=True)
    assert service.engine == "system"


# -- continuous conversation: exit-phrase detection -------------------------

from ui.dashboard import is_continuous_stop  # noqa: PLC0415, E402


def test_stop_phrase_detection():
    assert is_continuous_stop("stop")
    assert is_continuous_stop("Stop.")
    assert is_continuous_stop("  goodbye  ")
    assert is_continuous_stop("stop listening")
    assert is_continuous_stop("that's all for now")
    assert is_continuous_stop("END CONVERSATION!")


def test_normal_requests_do_not_end_session():
    assert not is_continuous_stop("stop the music")
    assert not is_continuous_stop("pause")
    assert not is_continuous_stop("what time is it")
    assert not is_continuous_stop("")
    assert not is_continuous_stop("stopwatch for 5 minutes")